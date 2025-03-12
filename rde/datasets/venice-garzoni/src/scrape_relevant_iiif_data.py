import json
import requests
from tqdm import tqdm
import os

def json_url_to_python_dict(url:str) -> dict:
    response = requests.get(url)
    return json.loads(response.text)

garzoni_pres_base = 'https://garzoni.org/iiif/pres/'
annot_box_format = garzoni_pres_base + '{man_code}/segments/{canvas_code}'
annot_list_format = garzoni_pres_base + '{man_code}/list/{canvas_code}'
def parse_annot_from_manifest_and_code_data(man_code:str, canvas_code:str) -> dict[str, dict]:
    # only extract contract mention from the annotation list.
    annot_list_url = annot_list_format.format(man_code=man_code, canvas_code=canvas_code)
    annot_list = json_url_to_python_dict(annot_list_url)
    line_id_contract = {v['on']: v['resource']['@id']  for v in annot_list['resources'] if v['resource']['@type'] == 'grz:ContractMention'}
   
    # clean urn:uuuid: from the keys and values of contract_mentions
    qr = lambda x: x.replace('urn:uuid:', '')
    line_id_contract = {qr(k): qr(v) for k, v in line_id_contract.items()}
    
    annot_box_url = annot_box_format.format(man_code=man_code, canvas_code=canvas_code) 
    annot_boxes = json_url_to_python_dict(annot_box_url)
    contract_id_box = {}
    for box in annot_boxes['objects']:
        if box['id'] in line_id_contract:
            contract_id_box[line_id_contract[box['id']]] = box['boundingBox']
    return contract_id_box

coll_man = json_url_to_python_dict('https://garzoni.org/iiif/pres/collection/top')
colls = [coll['@id'] for coll in coll_man['manifests']]

for i, man_url in enumerate(colls):
    man = json_url_to_python_dict(man_url)
    vals = []
    man_label = man['label']
    man_md = man['metadata']
    man_id = man['@id'].replace(garzoni_pres_base, '').split('/')[0]
    fp = 'manifests_v2/'+man_id + '.json'
    #not need to fetch the relevant information twice...
    if not os.path.exists(fp):
        print('Scraping manifest ', i+1, '/', len(colls))
        for m in tqdm(man['sequences'][0]['canvases']):
            label = m['label']
            m_img = m['images']
            if len(m_img) > 1:
                print('More than one image in canvas!', label)
            m_img = m_img[0]
            w = m_img['resource']['width']
            h = m_img['resource']['height']
            url = m_img['resource']['@id']
            media_type = m_img['resource']['format']
            annot_url = m['otherContent'][0]['@id']
            annot_elems = annot_url.replace(garzoni_pres_base, '').split('/')
            contracts = parse_annot_from_manifest_and_code_data(annot_elems[0], annot_elems[-1])
            vals.append([label, w, h, media_type, url, annot_url, contracts])
                
        with open(fp, 'w+') as f:
            json.dump({'label': man_label, 'metadata': man_md, 'pages': vals}, f, indent=4)
