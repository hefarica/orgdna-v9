"""Inventory controls without executing JavaScript or launching a browser.

This reports authored scope, never test success. Run again after UI changes and
review manual rows. Browser results live separately in artifacts/results.json.
"""
from collections import Counter
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
from matrix_classification import classify
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
VOID = {'input','img','br','hr','meta','link','source','area','base','embed','param','track','wbr'}
TAGS = {'button','input','select','textarea','a','summary'}
class Inventory(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.rows=[]; self.counts=Counter()
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        parent_page = next((a.get('id') for t,a in reversed(self.stack)
                            if 'page' in a.get('class','').split() or t=='dialog'), 'shell')
        if tag in TAGS:
            parent = next((a['id'] for t,a in reversed(self.stack) if a.get('id')), None)
            if attrs.get('id'): locator='#'+attrs['id']
            elif attrs.get('name'): locator=(('#'+parent+' ') if parent else '')+tag+'[name="'+attrs['name']+'"]'
            elif attrs.get('data-page'): locator='nav a[data-page="'+attrs['data-page']+'"]'
            elif attrs.get('data-cap-tab'): locator='[data-cap-tab="'+attrs['data-cap-tab']+'"]'
            elif attrs.get('href'): locator=(('#'+parent+' ') if parent else '')+'a[href="'+attrs['href']+'"]'
            else: locator=(('#'+parent+' ') if parent else '')+tag
            nth=self.counts[locator];self.counts[locator]+=1
            key=attrs.get('id') or attrs.get('name') or attrs.get('href') or tag
            self.rows.append({'feature':parent_page+': '+key,'page':parent_page,'source':'html','tag':tag,
              'locator':locator,'nth':nth,'type':attrs.get('type'),'name':attrs.get('name'),'scope':parent,
              'label_text':'',
              'field_constraints':{key:attrs[key] for key in ['required','readonly','min','max','step','minlength','maxlength','pattern'] if key in attrs},
              'structural_assertion':'Element is attached after navigating to page (details may be collapsed).',
              'browser_status':'NOT_RUN','functional_status':'MANUAL',
              'action':'Review label, focus, enabled state, input validation and intended action in an authorized isolated browser.',
              'expected':'State and feedback match the relevant local action; no unexpected transmission or DSH mutation.',
              'reason':'No dedicated behavior assertion assigned yet; static presence is not interaction coverage.'})
        if tag in TAGS and tag not in VOID:attrs['_matrix_row']=len(self.rows)-1
        if tag not in VOID:self.stack.append((tag,attrs))
    def handle_data(self,text):
        for _,attrs in self.stack:
            if '_matrix_row' in attrs:self.rows[attrs['_matrix_row']]['label_text']+=text
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.stack=self.stack[:i];break

# Explicit mappings distinguish meaningful behavior from mere inventory checks.
GROUPS = [
 ('generation.spec.cjs', ['generate','prepare-generation','confirm-generation','cancel-generation','generation-consent','generation-tokens','generation-batch','generation-response-mode','restore-design','recovery-exports','resume-design-draft','project-name','project-list','project-load','project-version','project-refresh','project-save-new'],
  'Prepare/review/approve/cancel/retry/reload or restore through visible controls.', 'Exact plan approval gates one inert provider call; stale or cancelled results cannot publish; recovery preserves native bytes.'),
 ('navigation.spec.cjs', ['org-search','zoom-in','zoom-out','zoom-fit','hierarchy-reset','cancel-inspector'],
  'Navigate and use keyboard, graph search/zoom or local hierarchy restoration.', 'Only target page shown; graph responds; dialog opens/closes and control states remain consistent.'),
 ('workflows.spec.cjs', ['forget-key','persist-key','source_kind','agent_count','council_concurrency','generate-offline','profile-search','department-filter','skill-status-filter','agent-name','close-inspector','save-profile','tools-allow','tools-deny','save-tool-policy','reset-tool-policy','subteam-name','subteam-type','subteam-scope','save-subteam','new-subteam','council-topic','council-objection','council-evidence','council-save','council-close','cap-manual-name','cap-manual-description','cap-manual-instructions','cap-manual-save','cap-library-query','cap-preview','cap-plan-discard','cap-clear','cap-assignment-action','cap-apply','evaluation-task','evaluation-timeout','evaluation-prepare','evaluation-start','discover-models','model-agent-model','save-model-assignment','inventory','export-definitions','export-implementation','dsh-refresh-status'],
  'Use the dedicated local workflow through real browser buttons and fields.', 'Local data, visible feedback or actual download matches the workflow assertion; fixture counters record no live provider calls.'),
]

def main():
    html=(ROOT/'web/index.html').read_text();parser=Inventory();parser.feed(html)
    for row in parser.rows:
        row['label_text']=' '.join(row['label_text'].split())
        if row['label_text']:row['feature']=row['page']+': '+row['label_text'][:140]
        if row['tag']=='summary':
            row.update(category='disclosure',action='Open and close the disclosure with pointer and keyboard.',expected='Correct details appear without invoking an API action.',reason='Disclosure control; inventoried structurally. Dedicated disclosure behavior not yet authored for every panel.')
        elif row['tag']=='a':
            row['category']='download' if '/download/' in row['locator'] else 'navigation_or_reference'
        elif row['tag'] in ('input','select','textarea'):row['category']='field'
        else:row['category']='action_button'
        scope=row.get('scope') or ''
        if scope.startswith(('performance','promotion','review')) or 'governance' in scope:
            row['reason']='Governance evidence/scoring/reviewer workflow needs further isolated interaction cases; backend tests do not constitute browser coverage.'
        elif any(k in scope for k in ('lease','coordination')):
            row['reason']='Local lease acquire/renew/release conflict behavior has no dedicated Chromium case yet.'
        elif any(k in row['locator'] for k in ('plugin-','cap-reference','cap-catalog','cap-ai','resource-')):
            row['reason']='Catalog/reference/recommendation workflow needs synthetic transport scenarios and dedicated interaction cases; external fetch or paid inference is not authorized by this suite.'
        marker=row['locator'][1:] if row['locator'].startswith('#') and ' ' not in row['locator'] else row.get('name')
        for filename, ids, action, expected in GROUPS:
            if marker in ids:
                row.update(functional_status='NOT_RUN',suite=filename,action=action,expected=expected,
                  reason='Executable Chromium behavior assertion authored; browser execution unavailable in delivery environment.')
        if 'data-page' in row['locator'] or 'data-cap-tab' in row['locator']:
            row.update(functional_status='NOT_RUN',suite='navigation.spec.cjs',action='Click navigation/tab; exercise history or tab keyboard controls.',expected='Selected state and visible page/panel agree.',reason='Authored; Chromium not run.')
        if row['page']=='exportaciones' and any(x in row['locator'] for x in ['dsh-','harness-','workbook','excel']):
            row['reason']='Only read-only fixture refresh/disabled guards are automated. Actual DSH, launcher, pairing, Excel and sensitive side effects require a separate authorized manual session.'
    dynamic = [
      ('inicio','#generation-retry','Double-click retry after failure','One fresh plan, checkbox clear, zero automatic confirmations','generation.spec.cjs'),
      ('inicio','#generation-diagnostic-download','Download failed-attempt diagnostic','Exact job filename, JSON format, scrubbed contents','generation.spec.cjs'),
      ('organigrama','.graph-node[role="button"]','Tab/Enter, click and filter','Inspector opens for existing profile','navigation.spec.cjs'),
      ('perfiles','.profile-card','Search and open card','Correct profile, exact save and dirty-cancel behavior','workflows.spec.cjs'),
      ('organigrama','#subteam-members input','Choose existing members','Roster size unchanged after save','workflows.spec.cjs'),
      ('council','#council-members button','Open member inspector','Existing member, no agent execution',None),
      ('habilidades','[data-cap-selection]','Select capability and preview/discard','Local assignment plan changes only after review','workflows.spec.cjs'),
      ('habilidades','[data-cap-target]','Select profiles or overlapping subteams','Exact deduplicated existing IDs enter plan; changed selection invalidates review','learning.spec.cjs'),
      ('habilidades','[data-resource-agent]','Select workflow result and preview','Correct per-agent workflow mapping',None),
      ('habilidades','.plugin-result button','Compare/install-document/proposal controls','No installation or external execution from proposals',None),
      ('habilidades','#cap-library-results button','Edit a local capability copy','New content-addressed item preserves prior item and assignment','learning.spec.cjs'),
      ('habilidades','#evaluation-runs button','Cancel/review synthetic command run','No real user command or provider execution',None),
      ('modelos','#model-table button','Choose exact synthetic model ID','Config field is updated without a paid call','workflows.spec.cjs'),
      ('modelos','.model-rank','Reject invalid priority and save exact rank','No invalid POST; rank 7 survives reload','coordination.spec.cjs'),
      ('council','#lease-list button','Renew/release isolated lease','Local lease counters/version and released status exact','coordination.spec.cjs'),
      ('perfiles','#merit-ranking button','Open scored profile inspector','Existing profile selected without changing evidence','governance.spec.cjs'),
      ('perfiles','#tool-catalog-list button','Propose exact tool allow/deny','No runtime tool grants',None),
      ('perfiles','#performance-authors input','Choose coauthor for recorded delivery','Coauthors excluded from reviewer options','governance.spec.cjs'),
      ('habilidades','#skill-proposals button','Update declared skill status','Manual status and evidence retained',None),
      ('habilidades','#remediation-list button','Cancel or advance recorded remediation','No mutation on cancellation; valid order and manual-only flags','learning.spec.cjs'),
      ('organigrama','#subteam-list button','Edit existing functional subteam','Exact roster/facilitator update without new agents',None),
      ('habilidades','.plugin-result input[type="checkbox"]','Compare up to three catalog candidates','Bounded comparison preserves identities',None),
    ]
    for page, locator, action, expected, suite in dynamic:
        parser.rows.append(dict(feature=page+': dynamic '+locator,page=page,source='javascript',locator=locator,
          browser_status='NOT_RUN',functional_status='NOT_RUN' if suite else 'MANUAL',suite=suite,
          action=action,expected=expected,reason='Authored, Chromium not run.' if suite else 'Dedicated interaction case still requires an authorized manual session; not claimed as automated.'))
    cases=json.loads((HERE/'authored-cases.json').read_text())['tests']
    corrections,families=classify(parser.rows,cases)
    value={'inventory_audit':{'prior_inventory_rows':397,'static_rows_preserved':381,
        'added_dynamic_families':6,'corrected_dynamic_families':[
          {'old':'.plugin-candidate button','new':'.plugin-result button'},
          {'old':'#governance-records button','new':'#merit-ranking button'},
          {'old':'#cap-library button','new':'#cap-library-results button'}],
        'locator_hardening':corrections,
        'notice':'Inventory repairs and field/family grouping are not increased behavioral or executed coverage.'},
      'behavior_families':families,
      'format':'orgdna-e2e-control-matrix','version':2,'browser_execution':'NOT_RUN',
      'scope_notice':'Inventory plus targeted interaction coverage. Neither every interaction nor accessibility conformance is claimed.',
      'source_hashes':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['web/index.html','web/app.js','web/style.css']},
      'counts':dict(Counter(row['functional_status'] for row in parser.rows)),
      'categories':dict(Counter(row.get('category','dynamic') for row in parser.rows)), 'controls':parser.rows}
    (HERE/'control-matrix.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'controls':len(parser.rows),'counts':value['counts'],'browser_execution':'NOT_RUN'}))
if __name__=='__main__':main()
