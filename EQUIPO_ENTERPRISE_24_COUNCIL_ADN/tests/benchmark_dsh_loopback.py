"""Measures real local transport; uses mock official services, never real DSH/LLM."""
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine.dsh_connection import DSHConnectionManager

def measure(fn, n=200):
    samples=[]
    for _ in range(n):
        start=time.perf_counter_ns();fn();samples.append((time.perf_counter_ns()-start)/1e6)
    samples.sort()
    return {'samples':n,'unit':'ms','p50':round(samples[math.ceil(n*.50)-1],3),'p95':round(samples[math.ceil(n*.95)-1],3),'p99':round(samples[math.ceil(n*.99)-1],3),'max':round(samples[-1],3)}

def main():
    proc=subprocess.Popen(['node',str(ROOT/'cordis_extension/tests/live_bridge_fixture.mjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    client=DSHConnectionManager()
    try:
        pair=json.loads(proc.stdout.readline())
        start=time.perf_counter_ns();client.connect(pair['port'],pair['pairing_code']);pair_ms=(time.perf_counter_ns()-start)/1e6
        for _ in range(10):client.status();client.read_profiles()
        result={'measured_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'scope':'Python↔Node real loopback HTTP/1.1 keep-alive with official-service doubles',
                'actual_dsh_runtime_tested':False,'actual_provider_or_llm_tested':False,'user_computer_tested':False,
                'python':platform.python_version(),'node':subprocess.check_output(['node','--version'],text=True).strip(),
                'pair_plus_initial_verified_handshake_ms':round(pair_ms,3),'authenticated_handshake':measure(client.status),
                'read_profiles_including_fresh_handshake':measure(client.read_profiles),
                'native_import_preview_including_handshake':measure(lambda:client.preview_import({'format':'agent-team-gui/definitions'})),
                'warning':'Transport/service-double measurements only. Not full DSH, native agent wakeup, model generation or end-to-end task latency.'}
        output=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'docs/dsh_loopback_benchmark.json'
        output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        client.disconnect();proc.stdin.close();proc.wait(timeout=5);proc.stdout.close();proc.stderr.close()
if __name__=='__main__':main()
