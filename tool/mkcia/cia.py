"""RSF 生成と makerom による CIA 化 (CFW 前提のため署名は makerom 既定のテスト鍵)。"""

from pathlib import Path
from typing import Optional

from .meta import Meta
from .proc import Log, find_tool, run

RSF_TEMPLATE = """\
BasicInfo:
  Title                   : "{title}"
  CompanyCode             : "00"
  ProductCode             : "{product_code}"
  ContentType             : Application
  Logo                    : None

TitleInfo:
  UniqueId                : 0x{unique_id:X}
  Category                : Application

Option:
  UseOnSD                 : true
  FreeProductCode         : true
  MediaFootPadding        : false
  EnableCrypt             : false
  EnableCompress          : true

AccessControlInfo:
  CoreVersion             : 2
  DescVersion             : 2
  ReleaseKernelMajor      : "02"
  ReleaseKernelMinor      : "33"
  UseExtSaveData          : false
  FileSystemAccess:
    - DirectSdmc
  IdealProcessor          : 0
  AffinityMask            : 1
  Priority                : 16
  MaxCpu                  : 0x9E
  MemoryType              : Application
  SystemMode              : 64MB
  CpuSpeed                : 804MHz
  EnableL2Cache           : true
  CanAccessCore2          : true
  HandleTableSize         : 0x200
  DisableDebug            : false
  EnableForceDebug        : false
  CanWriteSharedPage      : true
  CanUsePrivilegedPriority: false
  CanUseNonAlphabetAndNumber: true
  PermitMainFunctionArgument: true
  CanShareDeviceMemory    : true
  RunnableOnSleep         : false
  SpecialMemoryArrange    : true
  ResourceLimitCategory   : Application
  ServiceAccessControl:
    - APT:U
    - $ns:c
    - ac:u
    - cfg:u
    - dsp::DSP
    - fs:USER
    - gsp::Gpu
    - gsp::Lcd
    - hid:USER
    - ptm:u
    - y2r:u

SystemControlInfo:
  SaveDataSize            : 0KB
  RemasterVersion         : 0
  StackSize               : 0x40000
"""


def write_rsf(meta: Meta, dst: Path) -> Path:
    dst.write_text(
        RSF_TEMPLATE.format(
            title=meta.title[:7].replace('"', ""),  # ProductInfo の Title は最大 8 バイト程度
            product_code=meta.product_code,
            unique_id=meta.unique_id,
        ),
        encoding="utf-8",
    )
    return dst


def build_cia(
    elf: Path,
    rsf: Path,
    romfs_bin: Path,
    smdh: Path,
    banner: Path,
    meta: Meta,
    dst: Path,
    log: Optional[Log] = None,
) -> Path:
    major, minor, micro = meta.version
    run(
        [
            find_tool("makerom"), "-f", "cia", "-o", dst,
            "-elf", elf, "-rsf", rsf, "-icon", smdh, "-banner", banner,
            "-romfs", romfs_bin, "-exefslogo", "-target", "t", "-desc", "app:4",
            "-major", str(major), "-minor", str(minor), "-micro", str(micro),
        ],
        log,
    )
    return dst
