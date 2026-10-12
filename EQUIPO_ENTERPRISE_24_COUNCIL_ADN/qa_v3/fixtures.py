"""Synthetic fixtures only. Every mocked provider call is explicitly non-live."""
import copy
import hashlib
import json


def analysis_fixture():
    return {'repository':{'url':'https://github.com/example/qa-fixture','full_name':'example/qa-fixture','sha':'a'*40,'private':False},
            'repository_files':['README.md','src/service.py','tests/test_service.py'],
            'summary':'Repositorio sintético para QA; no describe una lectura real de GitHub.',
            'signals':[], 'coverage':{'files_read':3,'read_files':3,'safe_files_seen':3,'inventory_complete':True,'fixture':True},'input_digest':'d'*64}


def inventory_fixture():
    a=analysis_fixture()
    return {'repository':a['repository'],'files':[{'path':p,'snippet':'Contenido sintético de '+p,'content_sha256':hashlib.sha256(p.encode()).hexdigest(),'truncated':False} for p in a['repository_files']],
            'signals':[],'coverage':a['coverage'],'warnings':['FIXTURE OFFLINE: no live repository fetched.'],'limits':{'max_files':20,'max_bytes':250000},'tree':[{'path':p,'type':'file'} for p in a['repository_files']]}


def profile_fixture(index):
    n=index+1
    return {'name':f'Perfil_{n}','display_name':f'Persona Sintética {n}','role':'CEO' if index==0 else f'SPECIALIST_{n}',
            'title':f'Especialista de dominio funcional {n}','department':f'Dominio {n}',
            'mission':f'Diseñar y demostrar el contrato específico del dominio {n} con evidencia reproducible.',
            'personality':f'Persona ficticia rigurosa, con perspectiva analítica del dominio {n}.',
            'responsibilities':[f'Inspeccionar evidencia del dominio {n}',f'Revisar riesgos del contrato {n}',f'Proponer pruebas del componente {n}'],
            'deliverables':[f'Contrato verificable {n}',f'Plan de validación {n}',f'Informe de riesgos {n}'],
            'skills':[{'name':f'Competencia {n}.{k}','description':f'Objetivo de aprendizaje aplicado {n}.{k}; no competencia acreditada.','evidence_paths':['src/service.py']} for k in range(1,4)],
            'evidence_paths':['README.md','src/service.py'],
            'functional_roles':['consultant'] if index%2 else ['auditor'],
            'tool_preset_role':'manual_review',
            'cv':{'summary':f'Trayectoria enteramente ficticia para el dominio {n}, con capacidades objetivo pendientes de evaluación.',
                  'experience':[{'position':f'Rol simulado {n}.{k}','organization':f'Laboratorio ficticio {n}.{k}',
                                 'period':'Escenario de simulación','scope':f'Contrato especializado del dominio {n}.{k}',
                                 'achievements':[f'Resultado hipotético {n}.{k}, nunca demostrado como logro real.']} for k in (1,2)],
                  'education':[{'program':f'Maestría ficticia del dominio {n}','institution':f'Institución inventada {n}.1','modules':[f'Método {n}.1',f'Método {n}.2']},
                               {'program':f'Doctorado ficticio del dominio {n}','institution':f'Institución inventada {n}.2','modules':[f'Método {n}.3',f'Método {n}.4']}],
                  'certifications':[{'name':f'Evaluación objetivo ficticia {n}','acceptance':f'Superar pruebas del dominio {n} con revisión independiente; no otorgada.'}],
                  'languages':['Español objetivo','Inglés técnico objetivo'],
                  'working_style':[f'Razonamiento verificable {n}',f'Disenso documentado {n}']}}


def profile_specs(n):return [profile_fixture(i) for i in range(n)]


def design_result(n):
    return {'profile_specs':profile_specs(n),'analysis':analysis_fixture(),
            'provenance':{'provider':'deepseek-official','model':'fixture-model','source_kind':'github_repository','generation_method':'mock_only'},
            'audit':{'fixture':True,'actual_provider_calls':0},'status':'PROPOSED_REQUIRES_REVIEW'}


def api_profile(slot):
    row=profile_fixture(slot-1);row['name']=f'P{slot:02d}_Fixture';row['role']='CEO' if slot==1 else f'DOMAIN_{slot:02d}_FIXTURE'
    for item in row['cv']['education']:item['institution']='Institución ficticia '+str(slot)
    return row
