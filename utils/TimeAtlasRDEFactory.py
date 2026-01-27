from RDEModel import *
import requests
from tqdm import tqdm


RDE_TYPE_TO_STATIC_CLASS_DEF = {
    RDEType.HR.value: HR,
    RDEType.OBS.value: Obs,
    RDEType.POI.value: POI,
    RDEType.GEOM.value: Geometry,
    RDEType.DATASET.value: Dataset,
    RDEType.MAP.value: Map,
    RDEType.LAYER.value: Layer,
    RDEType.AREA.value: Area
}

class RDEFactory:

    entity_cache = {}

    def __init__(self, api_url: str):
        self.api_url = api_url
        # requests.get(f'{self.api_url}/status').raise_for_status()
        if api_url.endswith('/v1/'):
            # removing trailing slash as it makes the endpoint construction clearer.
            self.api_url = api_url[:-1]
        if not self.api_url.endswith('/v1'):
            raise ValueError('API URL must end with /v1')

        # test health of the API by querying the health endpoint
        resp = requests.get(f'{self.api_url}/health')
        if resp.status_code != 200:
            raise ConnectionError(f'Could not connect to TimeAtlas API at {self.api_url}. Status code: {resp.status_code}')
        
        self.entity_cache = {}

    def get_single_rde_object(self, endpoint: str, uuid: str) -> RDE:
        if uuid in self.entity_cache:
            return self.entity_cache[uuid]
        resp = requests.get(f'{self.api_url}/{endpoint}/{uuid}')
        resp.raise_for_status()
        data = resp.json()
        rde_type = data.get('rde_type')
        if rde_type is None and 'properties' in data and 'rde_type' in data['properties']:
            # special cases for geometries, as they are GeoJSON Feature objects
            rde_type = data['properties']['rde_type']
        if rde_type not in RDE_TYPE_TO_STATIC_CLASS_DEF:
            raise ValueError(f'Unknown RDE type: {rde_type}')
        res = RDE_TYPE_TO_STATIC_CLASS_DEF[rde_type].constructor_from_json_obj(data)
        self.entity_cache[uuid] = res
        return res


    def get_all_results_from_endpoint(self, endpoint: str, per_page: int = 1000) -> list[dict]:
        # the TimeAtlas API paginates results, so we need to loop until we get all results. 1000 is the maximal amount per page. 
        results = []
        page = 1
        while True:
            resp = requests.get(f'{self.api_url}/{endpoint}', params={'page': page, 'per_page': per_page}, headers={'Accept': 'application/json'})
            resp.raise_for_status()
            data = resp.json()
            results.extend(data['items'])

            if 'next' not in data or data['next'] is None:
                break
            page += 1

        return results
    
    def get_dataset(self, dataset_uuid: str) -> Dataset:
        # resp = requests.get(f'{self.api_url}/datasets/{dataset_uuid}')
        return self.get_single_rde_object('datasets', dataset_uuid)

    def get_dataset_by_slug(self, slug: str) -> Dataset:
        resp = requests.get(f'{self.api_url}/datasets', headers={'Accept': 'application/json'})
        data = resp.json()
        for dataset in data['items']:
            if dataset['slug'] == slug:
                ds = Dataset.constructor_from_json_obj(dataset)
                self.entity_cache[dataset['uuid']] = ds
                return ds
        raise ValueError(f'Dataset with slug {slug} not found')

    def generate_all_hr_from_dataset(self, dataset: Dataset) -> list[HR]:
        hr_jsons = self.get_all_results_from_endpoint('hr/search?query=&dataset_slug=' + dataset.slug, per_page=1000)
        hrs = [HR.constructor_from_json_obj(hr_json) for hr_json in hr_jsons]
        self.entity_cache.update({hr.uuid: hr for hr in hrs})
        return hrs

    # Waring: very slow. Waiting on a better API endpoint to retrieve all obs for a dataset
    def generate_obs_from_list_of_hr(self, hr_list: list[HR]) -> list[Obs]:
        obs_uuids = set()
        for hr in hr_list:
            for obs_ref in hr.documents:
                if isinstance(obs_ref, str):
                    obs_uuids.add(obs_ref)
                elif isinstance(obs_ref, Obs):
                    obs_uuids.add(obs_ref.uuid)
        obs_list = []
        for obs_uuid in tqdm(obs_uuids, desc='Fetching observations'):
            obs_list.append(self.get_single_rde_object('obs', obs_uuid))
        return obs_list

    # def generate_all_obs_from_dataset(self, dataset: Dataset) -> list[Obs]:
    #     # TODO: change the endpoint once I understand how to filter obs by dataset info
    #     obs_jsons = self.get_all_results_from_endpoint('obs/search?query=&dataset_id=' + dataset.uuid, per_page=100)
    #     return [Obs.constructor_from_json_obj(obs_json) for obs_json in obs_jsons]