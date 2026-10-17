"""Independent read-only product review; write only new review evidence."""
import datetime, hashlib, json, os, runpy, subprocess, sys, time
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
base = runpy.run_path(str(OUT.parent / 's0-20261017/run_baseline.py'))
env = dict(base['env'])
env.update(PYTHONPATH=os.pathsep.join([str(OUT.parent/'s0.1-20261017/offline_guard'), str(ROOT), str(ROOT/'tests')]),
           TIKTOKEN_CACHE_DIR=str(ROOT/'.venv/tiktoken-cache'),
           S01_NETWORK_AUDIT=str(OUT/'network-audit.txt'), AIROBOT_GO_MULTI_AGENT_ENABLED='false')
if __name__ == '__main__':
    mode = sys.argv[1]
    if mode in {'before', 'after'}:
        snapshot = base['snapshot'](ROOT)
        (OUT/f'source-{mode}.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2)+'\n')
        print(snapshot['source_manifest_sha256'])
    else:
        argv = [str(ROOT/'.venv/bin/python'), '-m', 'pytest',
                str(OUT/'probes.py') if mode.startswith('probes') else 'tests', '-q', '-ra',
                '--junitxml='+str(OUT/f'{mode}.xml')]
        if mode == 'docker': env['AIROBOT_TEST_DOCKER']='1'
        if mode.startswith('probes'): argv += ['-s']
        if mode == 'sandbox-probe': argv = [str(ROOT/'.venv/bin/python'), str(OUT/'docker_probe.py')]
        if mode == 'sandbox-control': argv = [str(ROOT/'.venv/bin/python'), str(OUT/'docker_probe.py'), '--control']
        started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        clock = time.monotonic()
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
        (OUT/f'{mode}.txt').write_text(output)
        (OUT/f'{mode}-command.json').write_text(json.dumps(dict(argv=argv, started_utc=started,
            exit_code=result.returncode, elapsed_seconds=time.monotonic()-clock,
            output_sha256=hashlib.sha256(output.encode()).hexdigest()), indent=2)+'\n')
        print(output[-12000:])
        sys.exit(result.returncode)
