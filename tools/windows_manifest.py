"""Deterministic AMD64 COFF manifest resource; no SDK, downloads or external tool.

One RT_MANIFEST / CREATEPROCESS_MANIFEST_RESOURCE_ID / neutral-language entry.
The linker relocates its RVA. Read the final PE resource tree back independently
so embedding XML as an ordinary string cannot pass the release check.
"""
import struct
from xml.etree import ElementTree


def check_manifest(data):
    root = ElementTree.fromstring(data)
    levels = root.findall('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
    if len(levels) != 1 or levels[0].attrib != {'level': 'asInvoker', 'uiAccess': 'false'}:
        raise ValueError('EXE must request asInvoker with uiAccess=false')


def manifest_object(data):
    check_manifest(data)
    directory = struct.pack('<IIHHHH', 0, 0, 0, 0, 0, 1)
    resource = (directory + struct.pack('<II', 24, 0x80000018)
                + directory + struct.pack('<II', 1, 0x80000030)
                + directory + struct.pack('<II', 0, 72)
                + struct.pack('<IIII', 88, len(data), 65001, 0) + data)
    resource += b'\0' * (-len(resource) % 4)
    raw_offset = 20 + 40
    relocation_offset = raw_offset + len(resource)
    symbol_offset = relocation_offset + 10
    header = struct.pack('<HHIIIHH', 0x8664, 1, 0, symbol_offset, 1, 0, 0)
    section = struct.pack('<8sIIIIIIHHI', b'.rsrc\0\0\0', 0, 0, len(resource),
                          raw_offset, relocation_offset, 0, 1, 0, 0x40000040)
    relocation = struct.pack('<IIH', 72, 0, 3)  # IMAGE_REL_AMD64_ADDR32NB
    symbol = struct.pack('<8sIhHBB', b'.rsrc\0\0\0', 0, 1, 0, 3, 0)
    return header + section + resource + relocation + symbol + struct.pack('<I', 4)


def embedded_manifest(pe):
    def u16(at): return struct.unpack_from('<H', pe, at)[0]
    def u32(at): return struct.unpack_from('<I', pe, at)[0]
    start = u32(60)
    if pe[:2] != b'MZ' or pe[start:start+4] != b'PE\0\0' or u16(start+4) != 0x8664:
        raise ValueError('AMD64 PE required')
    optional = start + 24
    if u16(optional) != 0x20B or u32(optional+108) < 3:
        raise ValueError('PE32+ resource directory required')
    section_start = optional + u16(start+20)
    sections = []
    for i in range(u16(start+6)):
        at = section_start + 40*i
        sections.append((u32(at+12), u32(at+16), u32(at+20)))

    def file_offset(rva, size):
        for base, length, offset in sections:
            if base <= rva and rva+size <= base+length and offset+rva-base+size <= len(pe):
                return offset+rva-base
        raise ValueError('Resource RVA outside PE sections')

    resource_rva, resource_size = struct.unpack_from('<II', pe, optional+112+2*8)
    if not resource_rva or not resource_size:
        raise ValueError('Missing Windows application manifest resource')
    base = file_offset(resource_rva, resource_size)

    def entry(relative, wanted, is_directory):
        if relative+16 > resource_size: raise ValueError('Resource tree out of bounds')
        at = base+relative
        named, numbered = u16(at+12), u16(at+14)
        if relative+16+8*(named+numbered) > resource_size: raise ValueError('Resource entries out of bounds')
        matches = []
        for index in range(named+numbered):
            key, target = struct.unpack_from('<II', pe, at+16+index*8)
            if key == wanted:
                if bool(target & 0x80000000) != is_directory: raise ValueError('Invalid manifest tree')
                matches.append(target & 0x7FFFFFFF)
        if len(matches) != 1: raise ValueError('Missing or duplicate manifest entry')
        return matches[0]

    directory = entry(entry(0, 24, True), 1, True)
    leaf = entry(directory, 0, False)
    if leaf+16 > resource_size: raise ValueError('Manifest data entry out of bounds')
    rva, size = struct.unpack_from('<II', pe, base+leaf)
    offset = file_offset(rva, size)
    data = pe[offset:offset+size]
    check_manifest(data)
    return data
