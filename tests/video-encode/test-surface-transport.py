#!/data/data/com.termux/files/usr/bin/python
"""Exercise a private daemon with real Android AHB-backed dma-bufs.

Needs Android API 29+, stock gralloc and FFmpeg. Enables TVA_SURFACE only in
its child daemon; never changes the installed desktop daemon or session.
Encoder checks use alternating 4K pictures and exact requested keyframes;
throughput checks submit 120 packets without per-frame CPU picture copies.
Optional decoder fixtures compare every frame by its returned input-unit
index, then time a separate run without CPU hashing. Fixtures must split
Annex-B parameter sets from pictures, as required by the daemon protocol.
"""
import argparse, array, ctypes as C, fcntl, mmap, os, socket, struct, subprocess, sys, threading, time
from pathlib import Path
parser=argparse.ArgumentParser(description="Private Android fd transport pixel/keyframe/throughput checks")
parser.add_argument('--daemon',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--crop',type=int,nargs=4,metavar=('X','Y','W','H'))
parser.add_argument('--decoder-assets',type=Path,help='h264/hevc .bin, .json packet positions and -expected.json unit-index MD5 files')
args=parser.parse_args()
out=args.out.resolve();out.mkdir(exist_ok=False)
w,h=3840,2160
cx,cy,ew,eh=args.crop if args.crop else (0,0,w,h)
assert min(cx,cy)>=0 and min(ew,eh)>=96 and cx+ew<=w and cy+eh<=h and not (cx|cy|ew|eh)&1
class Desc(C.Structure):_fields_=[('width',C.c_uint32),('height',C.c_uint32),('layers',C.c_uint32),('format',C.c_uint32),('usage',C.c_uint64),('stride',C.c_uint32),('rfu0',C.c_uint32),('rfu1',C.c_uint64)]
class Plane(C.Structure):_fields_=[('data',C.c_void_p),('pixel',C.c_uint32),('row',C.c_uint32)]
class Planes(C.Structure):_fields_=[('count',C.c_uint32),('planes',Plane*4)]
a=C.CDLL('/system/lib64/libandroid.so');n=C.CDLL('/system/lib64/libnativewindow.so')
a.AHardwareBuffer_allocate.argtypes=[C.POINTER(Desc),C.POINTER(C.c_void_p)]
a.AHardwareBuffer_lockPlanes.argtypes=[C.c_void_p,C.c_uint64,C.c_int,C.c_void_p,C.POINTER(Planes)]
a.AHardwareBuffer_unlock.argtypes=[C.c_void_p,C.c_void_p];a.AHardwareBuffer_release.argtypes=[C.c_void_p]
n.AHardwareBuffer_getNativeHandle.argtypes=[C.c_void_p];n.AHardwareBuffer_getNativeHandle.restype=C.POINTER(C.c_int)
d=Desc(w,h,1,35,0x100|0x200|3|0x30);b=C.c_void_p();assert a.AHardwareBuffer_allocate(C.byref(d),C.byref(b))==0
p=Planes();assert a.AHardwareBuffer_lockPlanes(b,0x30,-1,None,C.byref(p))==0
pitch=p.planes[0].row;uv=min(p.planes[1].data,p.planes[2].data)-p.planes[0].data
assert a.AHardwareBuffer_unlock(b,None)==0
handle=n.AHardwareBuffer_getNativeHandle(b);fd=os.dup(handle[3]);size=os.lseek(fd,0,2)
a.AHardwareBuffer_release(b)
meta=[0x3231564e,w,h,pitch,uv,size,cx,cy];print('metadata',meta,flush=True)
raw=mmap.mmap(fd,size)
# A changing luma/chroma pattern, two frames repeated to check reuse.
yrow=[bytes(32+(x//32*13+i*18)%170 for x in range(w)) for i in range(2)]
rowcache=[[row.translate(bytes(min(235,v+delta*7) for v in range(256))) for delta in range(16)] for row in yrow]
refs=[]
for i in range(2):
 luma=b''.join(rowcache[i][y//32%16][cx:cx+ew] for y in range(cy,cy+eh))
 refs.append(luma+bytes([70+i*40,170-i*30])*(ew*eh//4))
def fill(i):
 fcntl.ioctl(fd,0x40086200,struct.pack('Q',2|1))
 for y in range(h):raw[y*pitch:y*pitch+w]=rowcache[i][y//32%16]
 row=bytes([70+i*40,170-i*30])*(w//2)
 for y in range(h//2):raw[uv+y*pitch:uv+y*pitch+w]=row
 fcntl.ioctl(fd,0x40086200,struct.pack('Q',2|4))
def rec(s,n):
 data=b''
 while len(data)<n:
  part=s.recv(n-len(data))
  if not part:raise EOFError
  data+=part
 return data
def session(cid,w,h):
 s=socket.socket(socket.AF_UNIX);s.settimeout(20);s.connect(str(out/'daemon.sock'))
 words=[0x444d4400,3,cid,w,h,2]
 if cid in (5,6,8,9,10):words += [40000000,60,1]
 s.sendall(struct.pack('!%dI'%len(words),*words));status,mode,namelen=struct.unpack('!3I',rec(s,12));rec(s,(16 if namelen>>31 else 0)+(namelen&0x7fffffff));assert (status,mode)==(0,2),(status,mode)
 return s
log=open(out/'daemon.log','w');env=os.environ.copy();env['TVA_SURFACE']='1';env.pop('LD_LIBRARY_PATH',None);env.pop('LD_PRELOAD',None)
proc=subprocess.Popen([str(args.daemon.resolve()),'--sock',str(out/'daemon.sock'),'-v'],env=env,stdout=log,stderr=log)
try:
 for _ in range(200):
  if (out/'daemon.sock').exists():break
  assert proc.poll() is None
  time.sleep(.1)
 for cid,ext in [(5,'h264'),(6,'hevc')]:
  s=session(cid,ew,eh);packets=[];flags=[]
  for i in range(4):
   fill(i%2);s.sendall(struct.pack('!I',0x20000000|32|(0x80000000 if i==2 else 0)))
   assert s.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])==1
   s.sendall(struct.pack('!8I',*meta))
   length,flag,pts=struct.unpack('!3I',rec(s,12));packets.append(rec(s,length));flags.append(flag)
  assert [i for i,flag in enumerate(flags) if flag&1]==[0,2],flags;print(ext,'flags',flags,flush=True);s.sendall(b'\0'*4);s.close();(out/('encode.'+ext)).write_bytes(b''.join(packets))
 for cid,ext in [(5,'h264'),(6,'hevc')]:
  fill(0);s=session(cid,ew,eh);packets=[]
  def read_packets():
   for i in range(120):
    length,flag,pts=struct.unpack('!3I',rec(s,12));packets.append(rec(s,length))
  worker=threading.Thread(target=read_packets);worker.start();start=time.monotonic()
  for i in range(120):
   s.sendall(struct.pack('!I',0x20000000|32))
   s.sendmsg([b'F'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])
   s.sendall(struct.pack('!8I',*meta))
  worker.join();elapsed=time.monotonic()-start
  print('BENCH',ext,len(packets),elapsed,len(packets)/elapsed,flush=True)
  s.sendall(b'\0'*4);s.close();(out/('bench.'+ext)).write_bytes(b''.join(packets))
 (out/'source.nv12').write_bytes(b''.join(refs[i%2] for i in range(4)))
 import re
 for ext in ('h264','hevc'):
  stats=out/(ext+'.psnr')
  subprocess.run(['ffmpeg','-v','error','-r','60','-i',str(out/('encode.'+ext)),
   '-r','60','-f','rawvideo','-pixel_format','nv12','-video_size',f'{ew}x{eh}',
   '-i',str(out/'source.nv12'),'-filter_complex',
   f'[0:v]format=yuv420p,setparams=range=limited:colorspace=bt709[a];'
   f'[1:v]format=yuv420p,setparams=range=limited:colorspace=bt709[b];'
   f'[a][b]psnr=stats_file={stats}:eof_action=endall','-f','null','-'],check=True)
  lines=stats.read_text().splitlines();assert len(lines)==4,lines
  values=[float(v) for line in lines for v in re.findall(r'psnr_[yuv]:([0-9.inf]+)',line)]
  assert min(values)>35,(ext,values)
  print('PIXELS',ext,'minimum plane PSNR',min(values),flush=True)
  negative=out/'swapped.nv12'
  if not negative.exists():
   bad=[]
   for i in range(4):
    frame=bytearray(refs[i%2]);base=ew*eh
    frame[base::2],frame[base+1::2]=frame[base+1::2],frame[base::2]
    bad.append(frame)
   negative.write_bytes(b''.join(bad))
  stats=out/(ext+'.negative.psnr')
  subprocess.run(['ffmpeg','-v','error','-r','60','-i',str(out/('encode.'+ext)),
   '-r','60','-f','rawvideo','-pixel_format','nv12','-video_size',f'{ew}x{eh}',
   '-i',str(negative),'-filter_complex',
   f'[0:v]format=yuv420p,setparams=range=limited:colorspace=bt709[a];'
   f'[1:v]format=yuv420p,setparams=range=limited:colorspace=bt709[b];'
   f'[a][b]psnr=stats_file={stats}:eof_action=endall','-f','null','-'],check=True)
  bad_lines=stats.read_text().splitlines();assert len(bad_lines)==4,bad_lines
  assert all(min(float(v) for v in re.findall(r'psnr_[uv]:([0-9.inf]+)',line))<25 for line in bad_lines)
  print('CONTROL',ext,'swapped chroma rejected on every frame',flush=True)


 if args.decoder_assets:
  import hashlib,json,re
  for cid,ext in [(0,'h264'),(1,'hevc')]:
   assets=args.decoder_assets.resolve()
   unit_data=(assets/(ext+'.bin')).read_bytes()
   units=json.loads((assets/(ext+'.json')).read_text())
   expected=json.loads((assets/(ext+'-expected.json')).read_text())
   for verify in (True,False):
    s=session(cid,w,h);seen={};errors=[]
    def send_units():
     try:
      for offset,size in units:
       unit=unit_data[offset:offset+size]
       starts=[m.start() for m in re.finditer(b'\x00\x00\x00?\x01',unit)]+[len(unit)]
       picture=[]
       for left,right in zip(starts,starts[1:]):
        nal=unit[left:right];header=4 if nal[:4]==b'\x00\x00\x00\x01' else 3
        kind=(nal[header]&31) if ext=='h264' else ((nal[header]>>1)&63)
        if kind in ((7,8) if ext=='h264' else (32,33,34)):
         s.sendall(struct.pack('!I',len(nal))+nal)
        else:picture.append(nal)
       unit=b''.join(picture);s.sendall(struct.pack('!I',len(unit))+unit)
      s.sendall(b'\0'*4)
     except Exception as e:errors.append(str(e))
    worker=threading.Thread(target=send_units);start=time.monotonic();worker.start()
    for _ in units:
     width,height,kind,pts=struct.unpack('!4I',rec(s,16));assert kind==0xfffffffd,(width,height,hex(kind),pts)
     msg,anc,flags,_=s.recvmsg(1,socket.CMSG_SPACE(4));fds=array.array('i');fds.frombytes(anc[0][2]);dfd=fds[0]
     m=struct.unpack('!8I',rec(s,32));assert pts not in seen;seen[pts]=True
     if verify:
      data=mmap.mmap(dfd,m[5],prot=mmap.PROT_READ);fcntl.ioctl(dfd,0x40086200,struct.pack('Q',1|1));digest=hashlib.md5()
      for y in range(height):digest.update(data[y*m[3]:y*m[3]+width])
      for plane in range(2):
       for y in range(height//2):digest.update(data[m[4]+y*m[3]+plane:m[4]+y*m[3]+width:2])
      assert digest.hexdigest()==expected[str(pts)],(ext,pts,digest.hexdigest(),expected[str(pts)])
      fcntl.ioctl(dfd,0x40086200,struct.pack('Q',1|4));data.close()
     os.close(dfd)
    elapsed=time.monotonic()-start;worker.join();s.close();assert not errors,errors
    print('DECODE',ext,'verify',verify,'frames',len(seen),'seconds',elapsed,'fps',len(seen)/elapsed,flush=True)

finally:
 proc.terminate()
 try:proc.wait(timeout=10)
 except subprocess.TimeoutExpired:proc.kill();proc.wait()
 raw.close();os.close(fd);log.close()
