/** Pure read-only mapping of an explicitly supplied snapshot; never reads .agent-teams. */
export function inspectAgentTeamsMapping(manifest, snapshot, mapping) {
  const errors = []
  const known = new Set(manifest.members.map(m => m.member_id))
  const memberMap = mapping?.member_names ?? {}
  const captainMember = mapping?.captain_member_id
  if (snapshot?.id !== mapping?.team_id) errors.push('AgentTeams team ID does not match explicit binding')
  if (!known.has(captainMember)) errors.push('Captain must map to ONE existing organization member')
  const rows = [{ member_id: captainMember, runtime_name: 'captain', session_id: snapshot?.captainSessionId ?? null }]
  for (const member of snapshot?.members ?? []) {
    if (member.status === 'removed') continue
    const id = Object.hasOwn(memberMap, member.name) ? memberMap[member.name] : null
    if (!known.has(id)) errors.push(`Unmapped runtime member: ${member.name}`)
    rows.push({ member_id: id, runtime_name: member.name, session_id: member.id || null })
  }
  if (rows.length !== known.size || new Set(rows.map(r => r.member_id)).size !== known.size || rows.some(r => !known.has(r.member_id))) errors.push('One-to-one complete roster required; captain is INCLUDED in total N')
  const live = rows.map(r => r.session_id).filter(Boolean)
  if (new Set(live).size !== live.length) errors.push('Duplicate live session IDs')
  const tasks = (snapshot?.tasks ?? []).map(task => ({ native_task_id: task.id, native_attempt_id: task.attemptId ?? null, native_status: task.status, member_id: rows.find(r => r.runtime_name === task.assignee)?.member_id ?? null }))
  return {
    status: errors.length ? 'BLOCKED_MAPPING' : 'MAPPING_REVIEW_REQUIRED',
    organization_id: manifest.organization_id, team_id: snapshot?.id ?? null,
    rows, tasks, errors, halted: snapshot?.halted === true,
    host_identity_verified: false, snapshot_is_user_supplied: true,
    live_connection: false, creates_members: false, resumes_team: false,
    requires: 'Verify provenance and current sessions through a trusted host read-only seam; this snapshot alone cannot authenticate a session.',
  }
}
