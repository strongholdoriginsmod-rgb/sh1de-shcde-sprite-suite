"""Independent PNG/ZIP fixtures. Python standard library only; no editor code."""
from pathlib import Path
import io,json,struct,zlib,zipfile,hashlib
P=Path(__file__).parent/'fixtures';P.mkdir(exist_ok=True)
signature=b'\x89PNG\r\n\x1a\n'
def chunk(t,b):
 t=t.encode('ascii');return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
def png(w,h,depth,kind,interlace=0,filtering=0,transparency=True):
 channels={0:1,2:3,3:1,4:2,6:4}[kind];limit=(1<<depth)-1
 values=[];gold=bytearray();palette=[((i*41)%256,(i*17)%256,(i*113)%256) for i in range(min(1<<depth,256))]
 alpha=[i*19%256 for i in range(len(palette))]
 for y in range(h):
  row=[]
  for x in range(w):
   v=[(x*7+y*13+c*31)% (limit+1) for c in range(channels)]
   if kind==6:v[3]=[0,1,2,3,7,31,64,127,254,255][(x+y)%10]
   row.append(v)
   if kind==6:rgba=v
   elif kind==2:rgba=v+[0 if transparency and v==[0,31,62] else 255]
   elif kind==3:rgba=list(palette[v[0]])+[alpha[v[0]] if transparency else 255]
   elif kind==4:rgba=[v[0]]*3+[v[1]]
   else:rgba=[round(v[0]*255/limit)]*3+[0 if transparency and v[0]==0 else 255]
   gold.extend(rgba)
  values.append(row)
 passes=[(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)] if interlace else [(0,0,1,1)]
 raw=bytearray();bpp=max(1,(channels*depth+7)//8)
 def paeth(a,b,c):
  p=a+b-c;ds=[abs(p-a),abs(p-b),abs(p-c)];return [a,b,c][ds.index(min(ds))]
 for px,py,dx,dy in passes:
  xs=list(range(px,w,dx));ys=list(range(py,h,dy))
  if not xs or not ys:continue
  prev=bytes((len(xs)*channels*depth+7)//8)
  for j,y in enumerate(ys):
   samples=[q for x in xs for q in values[y][x]]
   row=bytearray((len(samples)*depth+7)//8)
   for i,q in enumerate(samples):row[(i*depth)//8]|=q << (8-depth-((i*depth)%8))
   f=j%5 if filtering=='cycle' else filtering;raw.append(f)
   for i,q in enumerate(row):
    a=row[i-bpp] if i>=bpp else 0;b=prev[i];c=prev[i-bpp] if i>=bpp else 0
    pred=[0,a,b,(a+b)//2,paeth(a,b,c)][f];raw.append((q-pred)&255)
   prev=row
 data=signature+chunk('IHDR',struct.pack('>IIBBBBB',w,h,depth,kind,0,0,interlace))
 if kind==3:data+=chunk('PLTE',bytes(v for rgb in palette for v in rgb))
 if transparency and kind in (0,2,3):data+=chunk('tRNS',struct.pack('>H',0) if kind==0 else struct.pack('>HHH',0,31,62) if kind==2 else bytes(alpha))
 data+=chunk('IDAT',zlib.compress(raw))+chunk('IEND',b'')
 return data,bytes(gold)
index=[]
for kind,depths in [(0,[1,2,4,8]),(2,[8]),(3,[1,2,4,8]),(4,[8]),(6,[8])]:
 for depth in depths:
  for inter in [0,1]:
   name=f'c{kind}_d{depth}_i{inter}'
   data,gold=png(17,13,depth,kind,inter,'cycle');(P/(name+'.png')).write_bytes(data);(P/(name+'.rgba')).write_bytes(gold);index.append(dict(name=name,width=17,height=13))
for f in range(5):
 name=f'filter_{f}';data,gold=png(11,9,8,6,0,f);(P/(name+'.png')).write_bytes(data);(P/(name+'.rgba')).write_bytes(gold);index.append(dict(name=name,width=11,height=9))
for w,h in [(1,1),(1,5),(5,1),(2,2),(3,3)]:
 name=f'adam_{w}_{h}';data,gold=png(w,h,8,6,1,'cycle');(P/(name+'.png')).write_bytes(data);(P/(name+'.rgba')).write_bytes(gold);index.append(dict(name=name,width=w,height=h))
(P/'index.json').write_text(json.dumps(index,indent=2))
for method,label in [(zipfile.ZIP_STORED,'store'),(zipfile.ZIP_DEFLATED,'deflate')]:
 with zipfile.ZipFile(P/(label+'.zip'),'w',method) as z:
  z.writestr('nested/tile_a-9.png',png(17,13,8,6)[0]);z.writestr('Größe/é.txt','Straße\n')
class NonSeekable(io.BytesIO):
 def seekable(self):return False
 def seek(self,*a):raise io.UnsupportedOperation('seek')
buf=NonSeekable()
with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('descriptor.txt','with descriptor')
(P/'descriptor.zip').write_bytes(buf.getvalue())
# Zip bombs are represented by a deliberately inconsistent declared size; no huge allocation.
with zipfile.ZipFile(P/'traversal.zip','w',zipfile.ZIP_STORED) as z:z.writestr('../evil.png',b'x')
with zipfile.ZipFile(P/'symlink.zip','w',zipfile.ZIP_STORED) as z:
 info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=0o120777<<16;z.writestr(info,'../elsewhere')
with zipfile.ZipFile(P/'case_collision.zip','w',zipfile.ZIP_STORED) as z:z.writestr('a.png',b'1');z.writestr('A.png',b'2')
with zipfile.ZipFile(P/'unicode_collision.zip','w',zipfile.ZIP_STORED) as z:z.writestr('é.png',b'1');z.writestr('e\u0301.png',b'2')
# Deliberately unsupported bit depth and animation marker.
a,g=png(1,1,8,6);ih=struct.pack('>IIBBBBB',1,1,16,6,0,0,0)
(P/'unsupported16.png').write_bytes(signature+chunk('IHDR',ih)+chunk('IDAT',zlib.compress(b'\0'+b'\0'*8))+chunk('IEND',b''))
(P/'apng.png').write_bytes(a[:33]+chunk('acTL',struct.pack('>II',1,0))+a[33:])
# Browser import series, masks and reference metadata; all are synthetic, not actual game IDs.
for sub in ['series','references','broken']:(P/sub).mkdir(exist_ok=True)
for i in range(3):
 data,g=png(16,24+i*2,8,6,0,'cycle');(P/'series'/f'body_source-{i+7}.png').write_bytes(data)
 # Mask carries data even where alpha is zero.
 data,g=png(16,24+i*2,8,6,0,'cycle');(P/'series'/f'body_source-{i+7}_m.png').write_bytes(data)
 (P/'references'/f'body_target-{i}.png').write_bytes(data)
(P/'source-meta.json').write_text(json.dumps({'pixelsPerUnit':64,'frames':[{'name':f'body_source-{i+7}','pivot':{'x':.25,'y':.125}} for i in range(3)]}))
(P/'target-meta.json').write_text(json.dumps({'pixelsPerUnit':64,'frames':[{'name':f'body_target-{i}','pivot':{'x':.375,'y':.25}} for i in range(3)]}))
(P/'mapping.csv').write_text('source,target,pivot_x,pivot_y,ppu,offset_x,offset_y\n'+''.join(f'body_source-{i+7}.png,body_target-{i},0.375,0.25,64,0,0\n' for i in range(3)))
bad=bytearray((P/'c6_d8_i0.png').read_bytes());bad[-1]^=1
(P/'broken'/'broken-0.png').write_bytes(bad)
print(f'Generated {len(index)} independent PNG references and archive/UI fixtures in {P}')

# Transparent-margin image with a noncentral anchor for reset/trim regressions.
raw=bytearray()
for y in range(64):
 raw.append(0)
 for x in range(64):raw.extend((97,112,129,255) if 20<=x<31 and 8<=y<25 else (0,0,0,0))
(P/'trim-0.png').write_bytes(signature+chunk('IHDR',struct.pack('>IIBBBBB',64,64,8,6,0,0,0))+chunk('IDAT',zlib.compress(raw))+chunk('IEND',b''))
(P/'trim-meta.json').write_text(json.dumps({'pixelsPerUnit':64,'frames':[{'name':'trim-0','pivot':{'x':.25,'y':.5}}]}))
