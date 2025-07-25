import pandas as pd

special_acronym_resolution = {
      'MC.Capricomus': 'MC.Capricornus',
      'SMaCel': 'SMaCe',
      'SzZac': 'SZac',
      'Szac': 'SZac',
      'SMFo': 'SMF',
      'PSMM.IMP': 'PSMM.MP',
      'PSMM.P': 'PSMM.MP',
      'SGIET': 'SGiET',
      'SMGFT': 'SMGFr',
      'CiN': 'CIN',
      'CorpD': 'Corp',
      'SMCarm': 'SMaCarm',
      'SEufM': 'SEuM',
      'SAnd': 'SAndL',
      'SAZIr': 'SAZir',
      'PSMUMP': 'PSMU.MP',
      'AC.Philìppicug': 'AC.Philippicus',
      'Deiberazioni': 'Deliberazioni',
      'SSGPXXXI': 'SSGP'
   }

def process_source_acronym(df: pd.DataFrame) -> pd.DataFrame:
   with open('dorigo_abbreviation.txt', 'r') as f:
      cont = f.readlines()

   cont = sorted([x.strip().replace('\n', '').split('(') for x in cont if x.strip() != ''])
   abbreviation_dict = {v2.strip(')'): v1.strip() for v1, v2 in cont }
   df['acronym_1'] = df['source'].apply(lambda x: x.split(',')[0])
   df['acronym'] = df['acronym_1'].apply(lambda x: ''.join([c for c in x if c.isalpha() or c == '.']))
   df['acronym'] = df['acronym'].apply(lambda x: special_acronym_resolution.get(x, x))
   df['is_abbreviation'] = df['acronym'].apply(lambda x: x in abbreviation_dict.keys())

   def resolve_source(r: pd.Series) -> str:
      if r['is_abbreviation']:
         resolve = abbreviation_dict[r['acronym']]
         return r['source'].replace(r['acronym_1'], resolve)
      else:
         return r['source']

   df['source_resolved'] = df.apply(resolve_source, axis=1)
   return df.drop(columns=['acronym_1', 'acronym', 'is_abbreviation'])
