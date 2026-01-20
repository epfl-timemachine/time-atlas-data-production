import requests
import json 
import os

endpoint_wkey = 'https://api.maptiler.com/geocoding/country.{country_code}.json?limit=3&key={api_key}'
country_max_code = 206

missing_country_code = [
    1207, # Nicaragua
    1208, # Costa Rica
    1209, # Panama
    1210, # Honduras
    1211, # Belize
    1212, # USA
    1213, # Mexico
    1214, # Mexico
    1215, # Guatemala
    1216 # Canada
]

remove_country_codes = [
    171, # israel
    173, # syria, single point version (real version is 173)
    80, # egypt
    69 # sudan
]

osm_urls_wd_id = {
    "https://nominatim.openstreetmap.org/search?q=Gaza Strip&polygon_geojson=1&format=jsonv2": "Q39760", # gaza strip
    "https://nominatim.openstreetmap.org/search?q=Israel&polygon_geojson=1&format=jsonv2": "Q801", # israel
    "https://nominatim.openstreetmap.org/search?q=Cisjordania&polygon_geojson=1&format=jsonv2": "Q36678", # west bank
    "https://nominatim.openstreetmap.org/search?q=Syria&polygon_geojson=1&format=jsonv2": "Q858",  # syria
    "https://nominatim.openstreetmap.org/search?q=Egypt&polygon_geojson=1&format=jsonv2": "Q79", # egypt
    "https://nominatim.openstreetmap.org/search?q=Sudan&polygon_geojson=1&format=jsonv2": "Q1049"  # sudan
}


def osm_url_to_geojson_feature(osm_url: str) -> dict:
    response = requests.get(osm_url, headers={'User-Agent': 'TimeAtlasDataProductionBot/1.0'})
    if response.status_code == 200:
        data = response.json()[0]
        id = data['place_id']
        geom = data['geojson']
    return geom, id

save_folder = 'src'
with open('maptiler_key.txt', 'r') as f:
    api_key = f.read().strip()

all_ranges = list(set(range(1, country_max_code + 1)).difference(set(remove_country_codes))) + missing_country_code

for osm_id, wd_id in osm_urls_wd_id.items():
    geometry, place_id = osm_url_to_geojson_feature(osm_id)
    if geometry:
        with open(f'{save_folder}/country_{place_id}.json', 'w', encoding='utf-8') as f:
            json.dump({'type': 'FeatureCollection',
                       'features': [{"type": "Feature", "properties": {"wikidata": wd_id}, "geometry": geometry }]}, f, ensure_ascii=False, indent=2)
    else:
        print(f'Failed to fetch data for OSM ID {osm_id}')

for i in all_ranges:
    country_code = f'{i:03}'
    endpoint = endpoint_wkey.format(country_code=country_code, api_key=api_key)
    response = requests.get(endpoint)
    if response.status_code == 200:
        data = response.json()
        if 'features' in data and len(data['features']) > 0:
            with open(f'{save_folder}/country_{country_code}.json', 'w', encoding='utf-8') as f:
                f.write(response.text)
            print(f'Successfully fetched data for country code {country_code}')
    else:
        print(f'Failed to fetch data for country code {country_code}, Status Code: {response.status_code}')

def language_dict_from_wikidata_id(wikidata_id):
    endpoint_url = "https://query.wikidata.org/sparql"
    query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX wd: <http://www.wikidata.org/entity/>

        SELECT DISTINCT ?label (lang(?label) as ?label_lang)
        {{
            wd:{wikidata_id} rdfs:label ?label
        }}
        """
    headers = {
        "User-Agent": "TimeAtlasDataProductionBot/1.0"
    }
    response = requests.get(endpoint_url, params={'query': query, 'format': 'json'}, headers=headers)
    if response.status_code == 200:
        results = response.json().get('results', {}).get('bindings', [])
        language_dict = {}
        for result in results:
            label = result['label']['value']
            label_lang = result['label_lang']['value']
            language_dict[label_lang] = label
        return language_dict
    else:
        print(f"Error fetching data from Wikidata for ID {wikidata_id}: {response.status_code}")
        return {}

code_to_country_labels = {}
for file in os.listdir('src'):
    if file.startswith('country_') and file.endswith('.json'):
        with open(os.path.join('src', file), 'r', encoding='utf-8') as f:
            data = json.load(f)
            wikidata_id = data['features'][0]['properties']['wikidata']
            lang_dict = language_dict_from_wikidata_id(wikidata_id)
            code_to_country_labels[file] = lang_dict
            print(f"File: {file}, Wikidata ID: {wikidata_id}, Languages: {lang_dict}")

with open('country_code_to_labels.json', 'w', encoding='utf-8') as f:
    json.dump(code_to_country_labels, f, ensure_ascii=False, indent=2)