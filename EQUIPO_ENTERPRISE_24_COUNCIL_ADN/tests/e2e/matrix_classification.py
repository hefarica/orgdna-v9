"""Source-level coverage taxonomy. An authored mapping is NEVER browser evidence."""
from collections import Counter, defaultdict
import json

GOVERNANCE_FORMS = {'performance-form','performance-review-form','external-reviewer-fields','promotion-form','promotion-review-form'}
LEARNING_FORMS = {'skill-register-form','skill-feedback-form','remediation-form'}
FAMILY_SCOPES = {
    'config-form':'configuration', 'source-git-ref':'configuration', 'key-form':'memory_credentials',
    'project-save-form':'project_versions','project-load-form':'project_versions',
    'profile-form':'profile_editing','permission-section':'tool_policy','inherit-tools-label':'tool_policy',
    'subteam-form':'subteams','subteam-editor':'subteams','performance-form':'governance_deliverables',
    'performance-review-form':'governance_review','external-reviewer-fields':'governance_review',
    'promotion-form':'governance_proposals','promotion-review-form':'governance_decisions',
    'governance-controls':'governance_drafts','lease-form':'local_coordination','council-form':'council_minutes',
    'cap-manual-form':'capability_library','cap-library':'capability_library','cap-library-search':'capability_library',
    'cap-selection-bar':'capability_assignment','cap-plan-review':'capability_assignment','cap-assignments':'capability_assignment',
    'resource-workflows':'resource_workflows','resource-consent-review':'resource_workflows','resource-assignment-review':'resource_workflows',
    'cap-llm-recommendations':'capability_ai_recommendations','cap-ai-review':'capability_ai_recommendations',
    'cap-reference-form':'public_reference_ingestion','cap-reference-panel':'public_reference_ingestion',
    'plugin-shop':'plugin_catalog','plugin-shop-search-form':'plugin_catalog','plugin-shop-comparison':'plugin_catalog',
    'plugin-shop-report-form':'plugin_report','plugin-report-runtime':'plugin_report',
    'skill-register-form':'skill_proposals','skill-feedback-form':'skill_feedback','remediation-form':'remediation',
    'evaluation-form':'evaluation_execution','evaluation-panel':'evaluation_execution','evaluation-review':'evaluation_execution',
    'cap-evidence':'capability_audit','model-assignment-form':'model_assignment','consent-box':'legacy_analysis_consent',
    'dsh-connect-form':'dsh_connection','dsh-connection':'dsh_connection','dsh-read-team-form':'dsh_readback',
    'dsh-harness':'dsh_harness','harness-pair-form':'dsh_harness','harness-review':'dsh_harness',
    'dsh-launcher':'dsh_launcher','dsh-launch-form':'dsh_launcher','excel':'excel_workbook',
    'cordis-extension':'cordis_exports','cordis-preflight':'cordis_exports','cordis-manifest':'cordis_exports',
    'cap-deployment-form':'capability_deployment','cap-deployment-review':'capability_deployment',
}
EXTERNAL = {'dsh_connection','dsh_readback','dsh_harness','dsh_launcher','excel_workbook',
            'public_reference_ingestion','plugin_catalog','plugin_report','capability_ai_recommendations',
            'capability_deployment','legacy_analysis_consent','evaluation_execution'}

def classify(rows, cases):
    corrections=[]; summary_counts=Counter()
    def mapped(row, suite, action, expected, prefix=None):
        row.update(functional_status='NOT_RUN',suite=suite,action=action,expected=expected,
            reason='Dedicated local behavior assertion authored; Chromium has NOT_RUN status. Input validation and every option are not implied.')
        row['case_ids']=[case['title'] for case in cases if case['file']==suite and (not prefix or case['title'].startswith(prefix))]
    for index,row in enumerate(rows):
        row['inventory_row_id']=f'control-{index+1:04d}'
        row['inventory_validity']='source_reviewed'
        scope=row.get('scope') or ''; loc=row['locator']; tag=row.get('tag'); label=row.get('label_text','')
        # Broad descendant indices count the wrong nested summaries. Label predicates
        # remain stable when SkillHub reparents whole sections during setup.
        if row['source']=='html' and tag=='summary':
            text=label.split('0 / 3')[0].strip() if 'Coordinar edición local por rutas' in label else label
            corrected='summary:has-text('+json.dumps(text,ensure_ascii=False)+')'
            nth=summary_counts[corrected];summary_counts[corrected]+=1
            row.update(original_locator=loc, original_nth=row.get('nth',0),locator=corrected,nth=nth,
                locator_basis='Normalized static summary label; dynamic lease count excluded.')
            corrections.append({'row_id':row['inventory_row_id'],'old_locator':loc,'old_nth':row['original_nth'],'new_locator':corrected,'kind':'summary_locator_hardening'})
        if row['source']=='html' and tag=='button' and label and ' ' in loc and not row.get('name'):
            # Name-less static buttons must not drift when earlier dynamic cards appear.
            row.update(original_locator=loc, original_nth=row.get('nth',0),
                locator=loc+':text-is('+json.dumps(label,ensure_ascii=False)+')',nth=0,
                locator_basis='Source scope plus exact static button text.')
        family=FAMILY_SCOPES.get(scope)
        if not family:
            if any(x in loc for x in ['generation-','prepare-generation','confirm-generation','cancel-generation','design-draft']):family='generation_consent_pipeline'
            elif 'lease-' in loc or 'coordination' in loc:family='local_coordination'
            elif 'model-rank' in loc or 'model-preferences' in loc:family='model_priorities'
            elif 'model-' in loc or 'discover-models' in loc:family='model_assignment'
            elif '/download/' in loc:family='local_downloads'
            elif 'data-page' in loc or 'data-cap-tab' in loc:family='navigation'
            elif 'subteam' in loc:family='subteams'
            elif row['page']=='profile-dialog':family='profile_editing'
            else:family=row['page']+'_remaining_controls'
        row['behavior_family']=family
        row['control_role']=('hidden_identity' if row.get('type')=='hidden' else
            'disclosure' if tag=='summary' else 'editable_field_or_option' if tag in {'input','select','textarea'} else
            'repeated_dynamic_action' if row['source']=='javascript' else 'link' if tag=='a' else 'action')
        if scope in GOVERNANCE_FORMS and tag!='summary':
            mapped(row,'governance.spec.cjs','Complete the synthetic deliverable/review/proposal form and submit through the UI.',
                'Exact records, score, retained review history and manual decision transitions match; hierarchy, permissions and runtime remain unchanged.','governance:')
        if loc=='#reset-governance-drafts':
            mapped(row,'governance.spec.cjs','Cancel then approve discarding a stale draft.','Cancel retains fields; approval clears fields/base version without deleting saved evidence.','governance: duplicate')
        if scope=='lease-form' or loc=='#refresh-coordination':
            mapped(row,'coordination.spec.cjs','Acquire or refresh a synthetic workspace lease; exercise SHA/TTL boundaries and conflicts.',
                'Lease paths and ownership are exact, no fourth writer or overlap is accepted, released records stay released.','coordination:')
        if loc in {'#save-model-preferences','.model-rank'}:
            mapped(row,'coordination.spec.cjs','Reject noninteger/out-of-range priorities, save rank 7 and reload.','No invalid request is sent; rank 7 persists without inference.','modelos:')
        if scope in LEARNING_FORMS and tag!='summary':
            mapped(row,'learning.spec.cjs','Save and inspect versioned synthetic skill/feedback or remediation records.',
                'Exact manual records persist, cancellation is inert and invalid transitions are rejected without installing or executing.','habilidades:')
        if loc in {'#cap-target-mode','#cap-manual-type','#cap-manual-references','#cap-manual-reset','#subteam-facilitator'}:
            mapped(row,'learning.spec.cjs','Choose exact recipients/type, validate reference URLs or discard a local editor draft.',
                'Selected/subteam recipients deduplicate exactly; invalid references never POST; reset leaves saved items intact.','habilidades:')
        if scope in {'key-form','project-save-form','cap-library-search'} and tag=='button':
            mapped(row,'workflows.spec.cjs','Submit the form in its existing dedicated authored workflow.',
                'Credential field clears, project version persists, or library search returns the named item as asserted.')
        if row.get('name')=='api_key':
            mapped(row,'workflows.spec.cjs','Enter only the known noncredential sentinel and save in memory.','Field clears; state/receipts contain no sentinel; credential persistence is false.','inicio: synthetic')
        if '/download/organization.json' in loc or (row['page']=='registro' and tag=='a' and '/download/' in loc):
            mapped(row,'workflows.spec.cjs','Save and parse the real browser download.','Organization IDs match native exports, or receipt JSON identifies synthetic provenance without credentials.')
        if not row.get('case_ids') and row.get('suite'):
            row['case_ids']=[case['title'] for case in cases if case['file']==row['suite']]
        if row.get('case_ids'):row['case_reference_scope']='Workflow/suite traceability; only named assertions prove a variant after an actual run.'
        row['coverage_scope']=('external_integration_unverified' if family in EXTERNAL else
            'authored_local_behavior' if row['functional_status']=='NOT_RUN' else 'structural_inventory_only')
        row['remaining_work']=('Real authorized integration and browser evidence required; current synthetic/guard coverage does not establish the real integration.' if family in EXTERNAL else
            'Browser execution required; only the variants named by the case assertions are covered in authored scope.' if row['functional_status']=='NOT_RUN' else
            'Shared disclosure reachability/keyboard variant, not a standalone business workflow.' if tag=='summary' else
            'Part of its named workflow; check serialization, individual option branches and constraints as relevant.' if tag in {'input','select','textarea'} else
            'Distinct action or repeated handler variant requires a meaningful assertion or authorized manual verification.')
    groups=defaultdict(list)
    for row in rows:groups[row['behavior_family']].append(row)
    families=[{'id':key,'inventory_rows':len(items),'statuses':dict(Counter(item['functional_status'] for item in items)),
               'roles':dict(Counter(item['control_role'] for item in items)),
               'browser_status':'NOT_RUN'} for key,items in sorted(groups.items())]
    return corrections,families
