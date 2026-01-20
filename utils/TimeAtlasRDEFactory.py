from RDEModel import *
import requests

class RDEFactory:

    def __init__(self, api_url: str):
        self.api_url = api_url
        # requests.get(f'{self.api_url}/status').raise_for_status()
        if api_url.endswith('/v1/'):
            # removing trailing slash as it makes the endpoint construction clearer.
            self.api_url = api_url[:-1]
        if not api_url.endswith('/v1'):
            raise ValueError('API URL must end with /v1')

    def get_all_results_from_endpoint(self, endpoint: str, per_page: int = 100) -> list[dict]:
        # the TimeAtlas API paginates results, so we need to loop until we get all results
        results = []
        page = 1
        while True:
            resp = requests.get(f'{self.api_url}/{endpoint}', params={'page': page, 'per_page': per_page}, headers={'Accept': 'application/json'})
            # checking the url of the request for debugging
            print(resp.url)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data['items'])

            if 'next' not in data or data['next'] is None:
                break
            page += 1

        return results
    
    def get_dataset(self, dataset_uuid: str) -> Dataset:
        resp = requests.get(f'{self.api_url}/datasets/{dataset_uuid}')
        resp.raise_for_status()
        data = resp.json()
        return Dataset.constructor_from_json_obj(data)

    def get_dataset_by_slug(self, slug: str) -> Dataset:
        resp = requests.get(f'{self.api_url}/datasets', headers={'Accept': 'application/json'})
        data = resp.json()
        for dataset in data['items']:
            if dataset['slug'] == slug:
                return Dataset.constructor_from_json_obj(dataset)
        raise ValueError(f'Dataset with slug {slug} not found')

    def generate_all_hr_from_dataset(self, dataset: Dataset) -> list[HR]:
        hr_jsons = self.get_all_results_from_endpoint('hr/search?query=&dataset_slug=' + dataset.slug, per_page=100)
        return [HR.constructor_from_json_obj(hr_json) for hr_json in hr_jsons]

    def generate_all_obs_from_dataset(self, dataset: Dataset) -> list[Obs]:
        # TODO: change the endpoint once I understand how to filter obs by dataset info
        obs_jsons = self.get_all_results_from_endpoint('obs/search?query=&dataset_id=' + dataset.uuid, per_page=100)
        return [Obs.constructor_from_json_obj(obs_json) for obs_json in obs_jsons]