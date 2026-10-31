"""실제 업무문서를 복제하지 않고 처음부터 만드는 가상 구조 시험자료."""
import argparse
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from budget_offline.numbers import KEY_FIELDS, HEADERS

HP='http://www.hancom.co.kr/hwpml/2011/paragraph'
HS='http://www.hancom.co.kr/hwpml/2011/section'


def key(dept='D001',project='P001',period='2026',metric='시행예산',budget='시행예산',dimension='전체',level='사업총액',fund='전체'):
    return dict(zip(KEY_FIELDS,(dept,project,period,budget,metric,dimension,level,fund)))


def row(k,raw,unit):
    return [k[x] for x in KEY_FIELDS]+[raw,unit]


def xlsx(path,rows,formula=None,header_row=3,hidden=False):
    wb=Workbook();ws=wb.active;ws.title='가상제출'
    ws['A1']='가상예산-v1'
    for c,h in enumerate(HEADERS,1):ws.cell(header_row,c,h)
    for r,values in enumerate(rows,header_row+1):
        for c,v in enumerate(values,1):
            cell=ws.cell(r,c,v)
            if isinstance(v,str):cell.data_type='s'
    if formula:ws.cell(header_row+1,9,formula)
    if hidden:ws.row_dimensions[header_row+1].hidden=True
    wb.save(path);wb.close()


def hwpx(path,rows,shift=False,unknown=False):
    def p(text):
        return '<hp:p paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>'+escape(str(text))+'</hp:t></hp:run></hp:p>'
    body=p('가상자료: 실제 업무자료가 아닙니다.')
    if shift:body+=p('위치 변경 시험용 앞 문단')*3
    body+=p('미확인양식-v2' if unknown else '가상예산-v1')
    body+='<hp:p><hp:run><hp:tbl id="1" rowCnt="'+str(len(rows)+1)+'" colCnt="10"><hp:sz width="50000" height="10000"/>'
    for ri,values in enumerate([HEADERS]+rows):
        body+='<hp:tr>'
        for ci,v in enumerate(values):
            body+=f'<hp:tc><hp:subList>{p(v)}</hp:subList><hp:cellAddr colAddr="{ci}" rowAddr="{ri}"/><hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="5000" height="1000"/><hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
        body+='</hp:tr>'
    body+='</hp:tbl></hp:run></hp:p>'
    section=f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'+body+'</hs:sec>'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype','application/hwp+zip',compress_type=zipfile.ZIP_STORED)
        z.writestr('version.xml','<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version" targetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="0"/>')
        z.writestr('META-INF/container.xml','<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></rootfiles></container>')
        z.writestr('Contents/content.hpf','<opf:package xmlns:opf="http://www.idpf.org/2007/opf"><opf:manifest><opf:item id="section0" href="section0.xml" media-type="application/xml"/></opf:manifest><opf:spine><opf:itemref idref="section0"/></opf:spine></opf:package>')
        z.writestr('Contents/section0.xml',section)
        z.writestr('Preview/PrvText.txt','가상 구조 시험용. 한컴오피스 렌더링 호환성은 미검증.')


def hwp_structure_fixture(path,text='가상부서 시행예산 1,000천원'):
    """CFB/OLE + HWP 5 헤더/압축 PARA_TEXT. 한컴 완전 문서 호환성 주장은 하지 않는다."""
    FREE=0xffffffff;END=0xfffffffe;FAT=0xfffffffd
    header=bytearray(512)
    header[:8]=bytes.fromhex('D0CF11E0A1B11AE1')
    struct.pack_into('<HHHHH',header,24,0x003e,3,0xfffe,9,6)
    struct.pack_into('<IIIIIIIII',header,40,0,1,1,0,4096,END,0,END,0)
    struct.pack_into('<109I',header,76,0,*([FREE]*108))
    fileheader=bytearray(4096);fileheader[:17]=b'HWP Document File'
    struct.pack_into('<II',fileheader,32,0x05000300,1)
    payload=(text+'\r').encode('utf-16le')
    record=struct.pack('<I',67|(1<<10)|(len(payload)<<20))+payload
    encoder=zlib.compressobj(wbits=-15)
    body=(encoder.compress(record)+encoder.flush()).ljust(4096,b'\0')
    docinfo=b'\0'*4096
    def entry(name,kind,start=END,size=0,left=FREE,right=FREE,child=FREE):
        b=bytearray(128);n=(name+'\0').encode('utf-16le');b[:len(n)]=n
        struct.pack_into('<HBBIII',b,64,len(n),kind,1,left,right,child)
        struct.pack_into('<IQ',b,116,start,size)
        return b
    directory=entry('Root Entry',5,child=1)+entry('FileHeader',2,3,4096,right=2)+entry('BodyText',1,child=3,right=4)+entry('Section0',2,11,4096)+entry('DocInfo',2,19,4096)
    directory=directory.ljust(1024,b'\0')
    fat=[FREE]*128;fat[0]=FAT;fat[1]=2;fat[2]=END
    for start in (3,11,19):
        for i in range(start,start+8):fat[i]=i+1 if i<start+7 else END
    path.write_bytes(header+struct.pack('<128I',*fat)+directory+fileheader+body+docinfo)


def generate(destination,departments=3,include_edges=True):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    normal=destination/'정상자료';normal.mkdir(exist_ok=True)
    keys=[];truth=[]
    for d in range(1,departments+1):
        dept=f'D{d:03d}'
        hr=[];xr=[]
        for metric,period,budget,hvalue,hunit,xvalue,xunit,expected,base in [
            ('시행예산','2026','시행예산','1,000','천원','1000000','원','1000000','KRW'),
            ('전년도예산','2025','시행예산','900000','원','900000','원','900000','KRW'),
            ('집행률','2026','집행','12.5','%','0.125','비율','0.125','ratio'),
            ('예산사용률','2026','집행','60','%','0.60','비율','0.60','ratio')]:
            k=key(dept=dept,metric=metric,period=period,budget=budget);keys.append(k)
            hr.append(row(k,hvalue,hunit));xr.append(row(k,xvalue,xunit))
            truth.append({'key':k,'expected_value':expected,'expected_unit':base,'after_manual_mapping':'정확 일치' if hunit==xunit else '변환 후 정확 일치','before_manual_mapping':'연결 불명','approved_by_default':False})
        hwpx(normal/f'{dept}_가상제출.hwpx',hr,shift=d%2==0)
        xlsx(normal/f'{dept}_가상제출.xlsx',xr,header_row=6 if d%2==0 else 3)
    (destination/'필수항목.json').write_text(json.dumps({'departments':[{'code':f'D{d:03d}','name':f'가상{d}부서'} for d in range(1,departments+1)],'keys':keys},ensure_ascii=False,indent=2),encoding='utf-8')
    (destination/'기대결과.json').write_text(json.dumps(truth,ensure_ascii=False,indent=2),encoding='utf-8')
    if include_edges:
        edge=destination/'주의자료';edge.mkdir(exist_ok=True)
        k=key()
        xlsx(edge/'D001_수정본.xlsx',[row(k,'1000001','원')])
        xlsx(edge/'수식캐시없음.xlsx',[row(key(project='FORMULA'),'','원')],formula='=500+500')
        xlsx(edge/'숨김행.xlsx',[row(key(project='HIDDEN'),'1000','원')],hidden=True)
        hwpx(edge/'새양식.hwpx',[row(key(project='UNKNOWN'),'1000','원')],unknown=True)
        for i,(raw,unit) in enumerate([('','원'),('0','원'),('-','원'),('해당 없음','원'),('약 1.2','억원'),('1000','')]):
            k=key(project=f'EDGE{i}')
            hwpx(edge/f'경계{i}.hwpx',[row(k,raw,unit)])
            xlsx(edge/f'경계{i}.xlsx',[row(k,raw,unit)])
        (edge/'손상.xlsx').write_bytes(b'broken file')
        hwp_structure_fixture(edge/'HWP5_구조시험_렌더링미검증.hwp')
    return truth


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination');parser.add_argument('--departments',type=int,default=3)
    args=parser.parse_args();generate(args.destination,args.departments)
