#!/data/data/com.termux/files/usr/bin/python
"""Private-server qualification; never installs a package or drives the live display."""
import argparse, array, json, math, os, socket, subprocess, time
from pathlib import Path

ap=argparse.ArgumentParser()
ap.add_argument('--candidate-prefix',type=Path,required=True)
ap.add_argument('--out',type=Path,required=True)
ap.add_argument('--seconds',type=int,default=120)
a=ap.parse_args()
if a.seconds<90:ap.error("--seconds must be at least 90 for the steady playback window")
O=a.out.absolute();O.mkdir(parents=True,mode=0o700,exist_ok=False)
prefix=a.candidate_prefix.absolute();base=os.environ.copy()
procs=[];logs=[];result={};p=None

def start(args,name,env):
 f=(O/(name+'.log')).open('w');logs.append(f)
 p=subprocess.Popen([str(x) for x in args],env=env,stdout=f,stderr=f);procs.append(p);return p

def pactl(*args):
 return subprocess.check_output(['pactl',*map(str,args)],env=client,text=True,timeout=10)

def capture_monitor():
 q=subprocess.Popen(['parec','--device=qualification.monitor','--raw','--format=s16le','--rate=48000','--channels=2','--latency-msec=30'],env=client,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 try:
  try:
   raw=q.communicate(timeout=1.2)[0]
  except subprocess.TimeoutExpired:
   q.terminate();raw=q.communicate(timeout=5)[0]
  data=array.array('h',raw[19200:115200])
  assert len(data)==48000
  return math.sqrt(sum(x*x for x in data)/len(data))
 finally:
  if q.poll() is None:q.terminate()
  q.wait(timeout=5)

try:
 for n in range(96,106):
  test={**base,'DISPLAY':':'+str(n)}
  if subprocess.run(['xdpyinfo'],env=test,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0:
   env=test;break
 else:raise RuntimeError('No free private X display')
 x=start(['Xvfb',env['DISPLAY'],'-screen','0','640x360x24','-nolisten','tcp'],'xvfb',env)
 for _ in range(100):
  if subprocess.run(['xdpyinfo'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
  if x.poll() is not None:raise RuntimeError('Private Xvfb failed')
  time.sleep(.1)
 fixture=O/'fixture.mkv'
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t',str(a.seconds+60),'-c:v','mpeg4','-q:v','5','-c:a','aac','-y',str(fixture)],check=True,timeout=60)
 sock=O/'pulse.sock';sock.unlink(missing_ok=True)
 runtime=O/'runtime';runtime.mkdir(exist_ok=True)
 server_env={**base,'PULSE_RUNTIME_PATH':str(runtime),'PULSE_STATE_PATH':str(O/'state'),'LD_LIBRARY_PATH':':'.join([str(prefix/'lib/pulseaudio'),str(prefix/'lib'),base.get('LD_LIBRARY_PATH','')])}
 server_env.pop('PULSE_SERVER',None)
 modules=str(prefix/'lib/pulseaudio/modules')
 server=start([prefix/'bin/pulseaudio','--daemonize=no','--exit-idle-time=-1','--use-pid-file=no','-n','--log-level=debug','--dl-search-path='+modules,'--load=module-aaudio-sink sink_name=qualification','--load=module-native-protocol-unix socket='+str(sock)+' auth-anonymous=1'],'server',server_env)
 client={**env,'PULSE_SERVER':'unix:'+str(sock),'LIVECD_MPV_GPU':'0','XDG_CONFIG_HOME':str(O/'config')}
 for _ in range(100):
  q=subprocess.run(['pactl','list','short','sinks'],env=client,capture_output=True,text=True)
  if q.returncode==0 and 'qualification' in q.stdout:break
  if server.poll() is not None:raise RuntimeError('Candidate server failed')
  time.sleep(.1)
 else:raise RuntimeError('Private PulseAudio readiness timeout')
 result['initial_sinks']=pactl('list','sinks')
 assert 'LATENCY' in result['initial_sinks']
 telemetry=O/'timing.lua'
 telemetry.write_text("local mp=require 'mp';local u=require 'mp.utils';local f=io.open("+json.dumps(str(O/'timing.jsonl'))+",'w');local function s() local r={wall=mp.get_time()};for _,k in ipairs({'time-pos','frame-drop-count','decoder-frame-drop-count','avsync','paused-for-cache','pause','seeking'})do r[k]=mp.get_property_native(k)end;f:write(u.format_json(r)..'\\n');f:flush()end;mp.add_periodic_timer(1,s);mp.register_event('shutdown',function()s();f:close()end)")
 ipc=O/'mpv.sock';ipc.unlink(missing_ok=True)
 p=start(['mpv','--no-config','--no-terminal','--vo=x11','--hwdec=no','--ao=pulse','--osc=no','--loop-file=inf','--input-ipc-server='+str(ipc),'--script='+str(telemetry),'--log-file='+str(O/'mpv.log'),str(fixture)],'player',client)
 for _ in range(100):
  inputs=pactl('list','short','sink-inputs')
  if inputs and ipc.exists():break
  if p.poll() is not None:raise RuntimeError('Player exited')
  time.sleep(.1)
 s=socket.socket(socket.AF_UNIX);s.settimeout(10);s.connect(str(ipc));f=s.makefile('rb');request=0
 def call(*args):
  global request
  request+=1;s.sendall((json.dumps({'command':args,'request_id':request})+'\n').encode())
  while True:
   r=json.loads(f.readline())
   if r.get('request_id')==request:
    assert r.get('error')=='success',r
    return r.get('data')
 t0=time.monotonic();time.sleep(3)
 index=inputs.split()[0]
 result['normal_rms']=capture_monitor()
 pactl('set-sink-input-volume',index,'50%');time.sleep(.4)
 result['half_volume_rms']=capture_monitor()
 pactl('set-sink-input-mute',index,1);time.sleep(.4)
 result['muted_rms']=capture_monitor()
 pactl('set-sink-input-mute',index,0);pactl('set-sink-input-volume',index,'100%')
 call('set_property','pause',True);time.sleep(1);call('set_property','pause',False);time.sleep(1)
 call('seek',30,'absolute');time.sleep(3)
 result['after_seek_time']=call('get_property','time-pos')
 second=start(['mpv','--no-config','--no-video','--ao=pulse','--length=4',str(fixture)],'second-client',client)
 time.sleep(1);result['concurrent_sink_inputs']=pactl('list','short','sink-inputs');result['second_exit']=second.wait(timeout=12)
 pactl('suspend-sink','qualification',1);time.sleep(1);pactl('suspend-sink','qualification',0)
 result['sink_samples']=[]
 while time.monotonic()-t0<a.seconds:
  if server.poll() is not None or p.poll() is not None:raise RuntimeError('Server/player exited during playback')
  result['sink_samples'].append(pactl('list','sinks'))
  time.sleep(5)
 result['output_drops']=call('get_property','frame-drop-count')
 result['final_avsync']=call('get_property','avsync')
 call('quit');f.close();s.close();result['player_exit']=p.wait(timeout=10)
 # Each unload/reload must release the old stream and recreate timestamp state.
 result['module_reload_cycles']=0
 for _ in range(3):
  modules=pactl('list','short','modules')
  idx=next(l.split()[0] for l in modules.splitlines() if '\tmodule-aaudio-sink\t' in l)
  pactl('unload-module',idx)
  pactl('load-module','module-aaudio-sink','sink_name=qualification')
  time.sleep(.3);result['module_reload_cycles']+=1
 result['hardware_timestamp_activations']=(O/'server.log').read_text().count('hardware presentation timestamps active')
 rows=[json.loads(l) for l in (O/'timing.jsonl').read_text().splitlines()]
 rows=[r for r in rows if r.get('frame-drop-count') is not None]
 steady=[r for r in rows if r['wall']>=max(40,rows[-1]['wall']-60)]
 result['steady_output_drops']=steady[-1]['frame-drop-count']-steady[0]['frame-drop-count']
 result['steady_seconds']=steady[-1]['wall']-steady[0]['wall']
 assert result['normal_rms']>50 and result['half_volume_rms']<result['normal_rms']/2 and result['muted_rms']<1
 assert len(result['concurrent_sink_inputs'].splitlines())==2 and result['second_exit']==0
 assert result['hardware_timestamp_activations']>=2
 assert result['steady_output_drops']==0
 result['ok']=True
except BaseException as e:
 result['error']=repr(e);result['ok']=False
 raise
finally:
 (O/'result.json').write_text(json.dumps(result,indent=2))
 for q in reversed(procs):
  if q.poll() is None:
   q.terminate()
   try:q.wait(timeout=5)
   except subprocess.TimeoutExpired:q.kill();q.wait()
 for log in logs:log.close()
 print(json.dumps({k:v for k,v in result.items() if k not in ('initial_sinks','sink_samples')},indent=2),flush=True)
