import pandas as pd
import uuid
from typing import Optional, Union
from collections import OrderedDict
from pandas.core.indexes.multi import MultiIndex
from enum import Enum


class SelectorType(Enum):
    POINT = 'PointSelector'
    SVG = 'SvgSelector'
    XYWH = 'SquareSelector'

class Selector():
  def __init__(self, tpe:SelectorType, value: Union[tuple[int,int], list[tuple[int,int]], tuple[int,int,int,int]]):
    self.type = tpe
    self.value = value
    if self.type is SelectorType.POINT and len(self.value) != 2:
        raise ValueError('Point selector should have 2 values')
    if self.type is SelectorType.XYWH and len(self.value) != 4:
        raise ValueError('XYWH selector should have 4 values')
    if self.type is SelectorType.SVG and type(self.value) != list:
        raise ValueError('SVG selector should be a list of number')
      

def generate_page_object(uuid_ns:uuid.UUID,
                        dataset_id:str,
                        range_idx:int, 
                        manifest_uuid:str,
                        label:str,
                        path:str,
                        format:str, 
                        height:int, 
                        width:int,
                        lan:str,
                        metadata: Optional[list[Union[tuple[str,str], tuple[str, str, Selector]]]] = None,
                        external_resource: Optional[str] = None) -> dict:
    canvas_uid = str(uuid.uuid5(uuid_ns, f"{dataset_id}_{manifest_uuid}_{range_idx}"))
    if external_resource:
        canvas_uid = (canvas_uid, external_resource)
    v = {
        "id": canvas_uid,
        "type": "Page",
        "range_idx": range_idx,
        "label": {lan: [label]},
        "format": format,
        "height": height,
        "width": width,
        "path": path
    }
    if metadata:
        v['metadata'] = metadata
    return v

def url_encoded_iiif_image_url(path:str) -> str:
    return f"https://image-timemachine.epfl.ch/iiif/3/{quote_plus(path)}"

from urllib.parse import quote_plus
def iiif_canvas_object_from_page_obj(uuid_ns: uuid.UUID, page_obj:dict, lan:str) -> dict:
    # it is here that the annotation is generated, should be in page_obj.
    # todo: make the annotation and page id modular, and not hardcoded to 1 (cf. webannotation model, for multiple annotations per page)

    url_encoded = url_encoded_iiif_image_url(page_obj['path'])
    metadata = page_obj.get('metadata', None)
    page_id = page_obj['id']
    if isinstance(page_id, tuple) or isinstance(page_id, list):
        # we're in the case were there is an external resource in the id.
        page_id = page_id[0]
      
    annot_page_idx = page_id+f"/{page_obj['range_idx']:04d}-image"
    obj = {
      "id": page_id,
      "type": "Canvas",
      "label": page_obj['label'],
      "height": page_obj['height'],
      "width": page_obj['width'],
      "items": [
        {
          "id": str(uuid.uuid5(uuid_ns, page_id+'/1')), 
          "type": "AnnotationPage",
          "items": [
            {
              "id": str(uuid.uuid5(uuid_ns, annot_page_idx)),
              "type": "Annotation",
              "motivation": "painting",
              "body": {
                "id": f"{url_encoded}/full/max/0/default.jpg",
                "type": "Image",
                "format": page_obj['format'],
                "height": page_obj['height'],
                "width": page_obj['width'],
                "service": [
                  {
                    "id": url_encoded,
                    "type": "ImageService3",
                    "profile": "level2"
                  }
                ]
              },
              "target": page_id
            }
          ]
        }
      ]
    }
    if metadata:
        obj['annotations'] = [generate_hr_commenting_annotation(uuid_ns, page_obj['id'], lan, metadata)]
    return obj

def generate_hr_commenting_annotation(uuid_ns:str, canvas_uid:Union[tuple[str, str], str], lan:str, hr_txt_selector:list[tuple[str,str, Optional[Selector]]]) -> dict:
    '''
    This function returns a simple annotation object with a textual body, that has the transcription of the HR
    as well as the link to the HR object.
    '''
    if len(hr_txt_selector[0]) == 2:
        # no selector present, casting the third value to None:
        hr_txt_selector = [(hr_id, txt, None) for hr_id, txt in hr_txt_selector]
    if isinstance(canvas_uid, str):
      target_obj = [{
        "id": canvas_uid,
        "type": "Canvas"
      }]
    elif isinstance(canvas_uid, tuple):
      target_obj = [{
        "id": canvas_uid[0],
        "type": "Canvas",
      },{
        "id": canvas_uid[1],
        "type": "ExternalResource",
      }
      ]
    return {
          "id": str(uuid.uuid5(uuid_ns, f'{canvas_uid}_hr_commenting_annotation')),
          "type": "AnnotationPage",
          "items": [
            {
              "id": str(uuid.uuid5(uuid_ns, f'{canvas_uid}_{hr_id}')),
              "type": "Annotation",
              "motivation": "commenting",
              "body": [{
                "type": "TextualBody",
                "language": lan,
                "format": "text/html",
                "value": txt
              },
              {
                "type": "rde:HistoricalRecord",
                "id": hr_id
              }],
              "target": target_obj if selector is None else generate_selector_template(canvas_uid, selector)
            } for hr_id, txt, selector in hr_txt_selector
          ]
        }

def int_tuple_list_to_svg_string(tpl: list[tuple[int,int]]) -> str:
    # example: "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g><path d='M270.000000,1900.000000 L1530.000000,1900.000000 L1530.000000,1610.000000 L1315.000000,1300.000000 L1200.000000,986.000000 L904.000000,661.000000 L600.000000,986.000000 L500.000000,1300.000000 L270,1630 L270.000000,1900.000000' /></g></svg>"
    # understanding the svg path command: https://developer.mozilla.org/en-US/docs/Web/SVG/Tutorial/Paths
    svg_preample = "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'><g>"
    path_preample = f"<path d='M{tpl[0][0]},{tpl[0][1]}"
    path_body = ' '.join([f'L{v[0]},{v[1]}' for v in tpl[1:]])
    path_body += f' L{tpl[0][0]},{tpl[0][1]}'
    return svg_preample + path_preample + path_body + "' /></g></svg>"


def generate_selector_template(source, sel:Selector) -> dict:
  if sel.type == SelectorType.POINT:
    return {
      "type": "SpecificResource",
      "source": source,
      "selector": {
        "type": sel.type.value,
        "x": sel.value[0],
        "y": sel.value[1]
      }
    }
  elif sel.type == SelectorType.SVG:
    return  {
      "type": "SpecificResource",
      "source": source,
      "selector": {
        "type": sel.type.value,
        "value": int_tuple_list_to_svg_string(sel.value)
      }
    }
  elif sel.type == SelectorType.XYWH:
    return f'{source}#xywh={sel.value[0]},{sel.value[1]},{sel.value[2]},{sel.value[3]}'
  else:
    raise ValueError('Selector type not recognized:', sel.type)

 

def generate_collection_manifest(uuid:str, label:dict[str, list[str]], manifests: dict[str, str]):
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": uuid,
        "type": "Collection",
        "label": label,
        "items": [
            {
                "id": manifest_id,
                "type": "Manifest",
                "label": label,
            } for manifest_id, label in manifests.items()
        ],
        "total": len(manifests),
        "metadata": [],
    }


def generate_manifest_object(uuid_ns: uuid.UUID, manifest_uid:str, label: dict[str, list[str]], default_lan:str, pages:list[dict], structures:Optional[dict] = None) -> dict:
    first_page = pages[0]
    man =  {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": manifest_uid,
        "type": "Manifest",
        "label": label,
        "thumbnail": [{
          "id": f"{url_encoded_iiif_image_url(first_page['path'])}/full/300,/0/default.jpg",
          "type": "Image"
        }
      ],
        "items": [iiif_canvas_object_from_page_obj(uuid_ns, p, default_lan) for p in pages]
    }
    if structures:
        man['structures'] = [structures]
    return man


# source: https://gist.github.com/dcragusa/1235704accde2152faa37113cafa95c0 then simplified for my use
def multiindex_to_nested_dict(df: pd.DataFrame) -> OrderedDict:
    if isinstance(df.index, MultiIndex):
        return OrderedDict((k, multiindex_to_nested_dict(df.loc[k])) for k in df.index.remove_unused_levels().levels[0])
    else:
        d = OrderedDict()
        for idx in df.index:
            d[idx] = df.loc[idx, 'canvas_id']
        return d
    
def ordered_dict_to_iiif_toc_structure(d: OrderedDict, lan:str, val:str, range_id_pref:str) -> dict:
    '''
    This function returns the IIIF ToC structure from the ordered dict.
    the ordered dict should be in the format "{"lvl1_label": {"lvl2_label": ...  {"lvln_label": [canvas_id1, canvas_id2,...,canvas_idn] }...}}.
    Accepts multiple leveld dict.
    '''
    res = {
        "id": range_id_pref,
        "type": "Range",
        "label": {lan: [val]},
        "items": None
    }
    itms = []
    for i, (k,v) in enumerate(d.items()):
        if isinstance(v, OrderedDict):
            itms.append(ordered_dict_to_iiif_toc_structure(v, lan, k, f'{range_id_pref}/{i+1}'))
        else:
            itms.append({
                "id": f'{range_id_pref}/{i+1}',
                "type": "Range",
                "label": {lan: [k]},
                "items": [{"id": canvas_id, "type": "Canvas"} for canvas_id in v]
            })
    res["items"] = itms
    return res