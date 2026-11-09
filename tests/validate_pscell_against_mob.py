"""Manual PSCell calculation parity check on current inputs (no production writes).

Run with venv Python from the Downloader root. Uses the installed MoB source as
an independent reference, without loading its application or changing its files.
All five notebook calculations execute; Excel/CSV exporters are intercepted.
The three common reports are compared across all common columns using sorted
row fingerprints, plus per-cell frequency referential checks. Export serialization
and worksheet limits are covered separately by test_audit_exports.py.
"""
import ast, sys, types, tempfile, hashlib, json, gc
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_workflow

original_read = pd.read_csv
results = {}
phase = 'downloader'
common = {'Missing_TermPointToGNB_PSCellChange.xlsx': ['Regional','UF','eNB','gNB','gNBId','Termpoint','IP_address','PLMN','Distance'],
'Missing_GUtranCellRelation_PSCellChange.csv': ['UF','eNB','CELL','Ancora','Tipo','gNB','GUtranSyncSignalFrequency','ssbFrequency','band','gNBId','nRCellDUId','cellLocalId','nRPCI','physicalLayerCellIdGroup','physicalLayerSubCellId','pLMNId_mcc','pLMNId_mnc','administrativeState_nr','ExternalGNodeBFunction','GUtranFreqRelationId','Regional','Tipo_Freq','Distance'],
'Missing_EUtranCellRelation_5g_4g_PSCellChange.xlsx': ['Regional','UF','gNB','NRCellCU','eNB','CELL','cellId','earfcndl','CGI','ExternalENodeBFunction','administrativeState','Tipo','Distance']}
def capture(frame, dest, *args, **kwargs):
 name=Path(dest).name
 if name in common:
  cols=common[name]
  assert set(cols)<=set(frame.columns),(name,set(cols)-set(frame.columns))
  d=frame[cols].copy()
  for col in cols:
   d[col]=d[col].fillna('').astype(str).str.replace(r'\.0$','',regex=True)
  hashes=np.sort(pd.util.hash_pandas_object(d,index=False).to_numpy())
  result={'rows':len(d),'hash':hashlib.sha256(hashes.tobytes()).hexdigest(),'columns':cols}
  if 'GUtranCellRelation' in name:
   result['unique_pairs']=len(d.drop_duplicates(['UF','eNB','CELL','gNB','nRCellDUId']))
   f=original_read('C:/Camilo/GUtranFreqRelation_46.txt',sep='\t',encoding='latin1',dtype=str).rename(columns={'EUtranCellFDD':'CELL','GUtranFrequency':'ssbFrequency'})
   keys=['UF','eNB','CELL','ssbFrequency']; idcol='GUtranFreqRelationId'
   for col in keys+[idcol]:f[col]=f[col].fillna('').str.replace(r'\.0$','',regex=True)
   check=d.merge(f[keys+[idcol]].drop_duplicates().assign(valid=True),on=keys+[idcol],how='left')
   result['nonempty_unmatched_ids']=int((check[idcol].ne('') & ~check.valid.eq(True)).sum())
  results.setdefault(phase,{})[name]=result
  print(phase,name,result,flush=True)
 Path(dest).parent.mkdir(parents=True,exist_ok=True); Path(dest).write_text('validation capture')

with tempfile.TemporaryDirectory(prefix='downloader_pscell_') as directory:
 root=Path(directory)
 def mapped(p):return root/str(p).replace('\\','/').replace('C:/','')
 item=next(i for i in audit_workflow.AUDITS if i['id']=='pscell-change-v10')
 with patch('audit_exports.write_audit_excel',capture),patch.object(pd.DataFrame,'to_csv',capture):
  audit_workflow.execute_audit(item,46,output_mapper=mapped)
 gc.collect()
 phase='mob'
 # Import the reference implementation into an isolated package. No MoB main,
 # config, network, outputs, or source files are changed.
 base=Path('C:/MoB_Tool_Box/mob_toolbox/app')
 pkg=types.ModuleType('reference_mob');pkg.__path__=[str(base)];sys.modules[pkg.__name__]=pkg
 import importlib
 sk=importlib.import_module('reference_mob.site_key');sk.mode=lambda:'cell'
 ref=importlib.import_module('reference_mob.mob_audit_pscell')
 ref._get_paths=lambda:(Path('C:/Camilo'),Path('C:/Camilo'),root/'reference')
 def read(path,*args,**kwargs):
  if Path(path).name in ['AddressIPv4.txt','5G_ExternalGUtranCell.txt']:path=Path('C:/Dumps/LTE_Total')/Path(path).name
  # Schema adapter only: Router is the same configured attribute as RouterId.
  if Path(path).name=='AddressIPv4.txt':
   kwargs['usecols']=['eNB','Router','IP_address']
   return original_read(path,*args,**kwargs).rename(columns={'Router':'RouterId'})
  return original_read(path,*args,**kwargs)
 original_exists = Path.exists
 def exists(path):
  if path.name in ['AddressIPv4.txt','5G_ExternalGUtranCell.txt']:
   return original_exists(Path('C:/Dumps/LTE_Total')/path.name)
  return original_exists(path)
 with patch.object(Path,'exists',exists),patch.object(pd,'read_csv',read),patch.object(pd.DataFrame,'to_excel',capture),patch.object(pd.DataFrame,'to_csv',capture):
  ref.run_audit()
 for name in common:
  assert results['downloader'][name]==results['mob'][name],(name,results['downloader'][name],results['mob'][name])
 print('ALL THREE PSCELL OUTPUTS MATCH MOB ON ALL COMMON COLUMNS',flush=True)
 (Path(__file__).resolve().parents[1] / '_tmp' / 'pscell_validation.json').write_text(json.dumps(results, indent=2), encoding='utf-8')

