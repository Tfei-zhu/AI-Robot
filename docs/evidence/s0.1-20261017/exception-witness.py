"""Observe original hardening test exception sites without changing tests or app code."""
import ast, collections, importlib.util, json, pathlib, sys, unittest
ROOT=pathlib.Path('/Users/xumanchun/Documents/agent项目/AI-Robot-latest')
FILE=ROOT/'tests/test_hardening.py'; OUT=ROOT/'docs/evidence/s0.1-20261017'
spec=importlib.util.spec_from_file_location('original_hardening',FILE); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
raises={}
for node in ast.walk(ast.parse(FILE.read_text())):
 if isinstance(node,ast.Raise) and isinstance(node.exc,ast.Call) and getattr(node.exc.func,'id',None)=='RuntimeError':
  raises[node.lineno]=ast.literal_eval(node.exc.args[0])
observed=collections.Counter(); stream_tokens=[]
def trace(frame,event,arg):
 if event=='exception' and frame.f_code.co_filename==str(FILE):
  kind,exc,tb=arg
  if frame.f_lineno in raises and isinstance(exc,RuntimeError): observed[(frame.f_lineno,str(exc))]+=1
 return trace
original_stream=module.chat_module.stream_chat
async def observed_stream(*args,**kwargs):
 stream=original_stream(*args,**kwargs)
 try:
  async for event in stream:
   if len(args)>1 and args[1]=='failed-stream': stream_tokens.append(dict(event))
   yield event
 finally: await stream.aclose()
# Only the stream-failure test is wrapped to observe emitted events; all other tests stay identical.
from unittest.mock import patch
class WitnessResult(unittest.TextTestResult):
 def startTest(self,test):
  super().startTest(test)
  if test._testMethodName=='test_stream_failure_does_not_commit_partial_answer':
   self._observer_patch=patch.object(module.chat_module,'stream_chat',observed_stream); self._observer_patch.start()
 def stopTest(self,test):
  if test._testMethodName=='test_stream_failure_does_not_commit_partial_answer': self._observer_patch.stop()
  super().stopTest(test)
sys.settrace(trace)
try: result=unittest.TextTestRunner(verbosity=2,resultclass=WitnessResult).run(unittest.defaultTestLoader.loadTestsFromModule(module))
finally: sys.settrace(None)
missing=[{'line':line,'message':message} for line,message in raises.items() if observed[(line,message)]==0]
tokens=[e.get('content') for e in stream_tokens if e['type']=='token']
report={'expected_runtime_error_sites':raises,'observed':[{'line':line,'message':msg,'count':count} for (line,msg),count in sorted(observed.items())], 'missing':missing,'stream_failure_events':stream_tokens,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped)}
(OUT/'exception-witness.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
assert result.wasSuccessful()
assert not missing,missing
assert '部分答案' in tokens,tokens
assert sum(e['type']=='error' for e in stream_tokens)==1
print('PASS: all original RuntimeError raise sites reached; partial answer token observed before intended 流中断; original assertions preserved')
