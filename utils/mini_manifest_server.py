from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
import os
import json

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'
app.config['JSON_AS_ASCII'] = False # to serve files in utf-8

LOCALHOST = 'http://127.0.0.1'
PORT = 5000
SERVER_URL = f'{LOCALHOST}:{PORT}'

@app.route('/manifest/<fp>', methods=['GET'])
def manifest(fp: str): 
    if request.method != 'GET':
        return f'Unknown method, this endpoint only accepts GET methods.', 405
    return resource('manifests', fp)

@app.route('/collection/<fp>', methods=['GET'])
def collection(fp: str): 
    if request.method != 'GET':
        return f'Unknown method, this endpoint only accepts GET methods.', 405
    return resource('collections', fp)

def resource(resource:str, fp: str):
    if resource != 'manifests' and resource != 'collections':
        return f'Unknown resource, this endpoint only accepts /manifest or /collection', 405
    if not fp.endswith('.json'):
        fp = fp + '.json'
    file_path = os.path.join(f'data/iiif/{resource}', fp)
    if not os.path.exists(file_path):
        return f'File {file_path} does not exists on the disk', 404
    with open(file_path, encoding='utf-8') as f:
        txt = f.read()

    txt = txt.replace('"target": "', f'"target": "{SERVER_URL}/')
    # for the annotations
    txt = txt.replace('"source": "', f'"source": "{SERVER_URL}/')
    
    # hacky way to have only the id on non images url being prefixed by the server url
    if resource == 'manifests':
        txt = txt.replace('"id": "', f'"id": "{SERVER_URL}/')
        txt = txt.replace(f'"id": "{SERVER_URL}/http', '"id": "http')
        manif_content = json.loads(txt)
        manif_content['id'] = f'{SERVER_URL}/manifest/{fp}'
    else:
        txt = txt.replace('"id": "', f'"id": "{SERVER_URL}/manifest/')
        manif_content = json.loads(txt)
        manif_content['id'] = f'{SERVER_URL}/collection/{fp}'
    return jsonify(manif_content)
    
if __name__ == "__main__":
    app.run(port=PORT)