"""Exact-consent AI recommendation fixtures. No paid/external requests."""
import copy,json,unittest
from engine import capability_recommendations as r,providers

def organization():
    return {'organization_id':'qa-org','state_version':1,'agents':[{'id':'qa-agent-'+str(i),'role':'Evidence reviewer','mission':'Review static evidence','evidence_paths':['doc-'+str(i)]} for i in range(3)]}
def candidates():
    return [{'id':'qa-capability','name':'Evidence review','description':'Reference methods only','kind':'skill_instructions','content_hash':'a'*64,'tool_needs':['files.read'],'provenance':{'type':'user_authored','source_id':'qa-source'}}]
class Fixture:
    def __init__(self,mutate=None):self.calls=[];self.mutate=mutate
    def __call__(self,method,url,headers,body,timeout,max_bytes):
        payload=json.loads(body);self.calls.append(payload)
        context=json.loads(payload['messages'][1]['content'].split('UNTRUSTED_CONTEXT\n',1)[1].split('\nEND_UNTRUSTED_CONTEXT')[0])
        agents=[{'agent_id':a['id'],'recommendations':[{'candidate_id':'qa-capability','rationale':'Método relacionado con la revisión de evidencia.','source_evidence':['qa-source'],'skill_type':'skill_instructions','needed_tools':['files.read'],'fit':'unknown','confidence':'low'}],'gaps':['Adecuación pendiente de pruebas.']} for a in context['agents']]
        value={'agents':agents}
        if self.mutate:self.mutate(value,len(self.calls))
        answer={'choices':[{'message':{'role':'assistant','content':json.dumps(value)},'finish_reason':'stop'}]}
        return 200,{},json.dumps(answer).encode()

class IndependentRecommendationTests(unittest.TestCase):
    def setUp(self):self.org=organization();self.candidates=candidates()
    def consent(self,**kw):
        c=r.prepare_recommendation_consent(self.org,self.candidates,'deepseek','fixture-model',**kw);c.update(confirmed=True,data_reviewed=True,budget_acknowledged=True);return c
    def call(self,c,f,**kw):return r.recommend_with_llm(self.org,self.candidates,'deepseek','fixture-model','QA_SYNTHETIC_KEY',c,transport=f,**kw)
    def test_preparation_and_baseline_are_no_network_no_activation(self):
        c=r.prepare_recommendation_consent(self.org,self.candidates,'deepseek','fixture-model')
        self.assertFalse(c['confirmed']);self.assertEqual(c['planned_requests'],1)
        b=r.baseline_recommendations(self.org,self.candidates);self.assertEqual(b['audit']['requests'],0);self.assertFalse(b['installed']);self.assertFalse(b['runtime_verified'])
    def test_exact_ids_and_single_consumed_batch(self):
        c=self.consent(batch_size=1,max_requests=3);f=Fixture();result=self.call(c,f,batch_size=1,max_requests=3)
        self.assertEqual(len(f.calls),3);self.assertEqual([a['agent_id'] for a in result['agents']],[a['id'] for a in self.org['agents']]);self.assertEqual(result['status'],'PROPOSED_NOT_TESTED');self.assertFalse(result['active'])
        with self.assertRaises(providers.ConsentRequired):self.call(c,f,batch_size=1,max_requests=3)
        self.assertEqual(len(f.calls),3)
    def test_changed_candidate_model_or_org_invalidates_before_network(self):
        for change in ('candidate','organization','model'):
            c=self.consent();f=Fixture();org=copy.deepcopy(self.org);cs=copy.deepcopy(self.candidates);model='fixture-model'
            if change=='candidate':cs[0]['description']='Changed after approval'
            elif change=='organization':org['agents'][0]['mission']='Changed after approval'
            else:model='other-model'
            with self.assertRaises(providers.ConsentRequired):r.recommend_with_llm(org,cs,'deepseek',model,'QA_SYNTHETIC_KEY',c,transport=f)
            self.assertFalse(f.calls)
    def test_invented_agent_candidate_tool_and_evidence_rejected(self):
        def agent(v,_):v['agents'][0]['agent_id']='invented'
        def candidate(v,_):v['agents'][0]['recommendations'][0]['candidate_id']='invented'
        def tool(v,_):v['agents'][0]['recommendations'][0]['needed_tools']=['admin.exec']
        def evidence(v,_):v['agents'][0]['recommendations'][0]['source_evidence']=['doc-2']
        def installed(v,_):v['agents'][0]['recommendations'][0]['rationale']='El plugin está instalado.'
        for mutate in (agent,candidate,tool,evidence,installed):
            with self.subTest(mutate=mutate.__name__),self.assertRaises(r.RecommendationError):self.call(self.consent(),Fixture(mutate))
    def test_second_batch_failure_stops_without_publishing_partial(self):
        def mutate(value,n):
            if n==2:value['agents'][0]['recommendations'][0]['candidate_id']='invented'
        c=self.consent(batch_size=1,max_requests=3);f=Fixture(mutate)
        with self.assertRaises(r.RecommendationError) as caught:self.call(c,f,batch_size=1,max_requests=3)
        self.assertEqual(len(f.calls),2);self.assertTrue(c['_consumed']);self.assertEqual(caught.exception.audit['requests'],2)
    def test_cancel_and_current_state_change_stop_further_calls(self):
        c=self.consent(batch_size=1,max_requests=3);f=Fixture()
        with self.assertRaises(r.RecommendationError):self.call(c,f,batch_size=1,max_requests=3,cancel_check=lambda:len(f.calls)>=1)
        self.assertEqual(len(f.calls),1)
        c=self.consent();f=Fixture();changed=copy.deepcopy(self.org);changed['state_version']=2
        with self.assertRaises(r.RecommendationError):self.call(c,f,current_organization=lambda:changed)
        self.assertFalse(f.calls)
    def test_known_session_secret_never_transmitted(self):
        self.candidates[0]['description']='QA_SYNTHETIC_KEY'
        c=self.consent();f=Fixture()
        with self.assertRaises(r.RecommendationError):self.call(c,f)
        self.assertFalse(f.calls)

if __name__=='__main__':unittest.main()
