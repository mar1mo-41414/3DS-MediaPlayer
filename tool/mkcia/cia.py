"""RSF 生成と makerom による CIA 化 (CFW 前提のため署名は makerom 既定のテスト鍵)。"""

from pathlib import Path
from typing import Optional

from .meta import Meta
from .proc import Log, find_tool, run

# 実機で動く homebrew CIA の定番構成に合わせた RSF。
# 注意: エミュレータは権限を検査しないので、SystemCallAccess / MemoryMapping / IORegisterMapping /
# FileSystemAccess が欠けていても動いてしまうが、実機では起動時に落ちる (HISTORY.md 参照)。
_SYSCALLS = {
    "ControlMemory": 1, "QueryMemory": 2, "ExitProcess": 3, "GetProcessAffinityMask": 4,
    "SetProcessAffinityMask": 5, "GetProcessIdealProcessor": 6, "SetProcessIdealProcessor": 7,
    "CreateThread": 8, "ExitThread": 9, "SleepThread": 10, "GetThreadPriority": 11,
    "SetThreadPriority": 12, "GetThreadAffinityMask": 13, "SetThreadAffinityMask": 14,
    "GetThreadIdealProcessor": 15, "SetThreadIdealProcessor": 16, "GetCurrentProcessorNumber": 17,
    "CreateMutex": 19, "ReleaseMutex": 20, "CreateSemaphore": 21, "ReleaseSemaphore": 22,
    "CreateEvent": 23, "SignalEvent": 24, "ClearEvent": 25, "CreateTimer": 26, "SetTimer": 27,
    "CancelTimer": 28, "ClearTimer": 29, "CreateMemoryBlock": 30, "MapMemoryBlock": 31,
    "UnmapMemoryBlock": 32, "CreateAddressArbiter": 33, "ArbitrateAddress": 34, "CloseHandle": 35,
    "WaitSynchronization1": 36, "WaitSynchronizationN": 37, "DuplicateHandle": 39,
    "GetSystemTick": 40, "GetHandleInfo": 41, "GetSystemInfo": 42, "GetProcessInfo": 43,
    "GetThreadInfo": 44, "ConnectToPort": 45, "SendSyncRequest1": 46, "SendSyncRequest2": 47,
    "SendSyncRequest3": 48, "SendSyncRequest4": 49, "SendSyncRequest": 50, "GetProcessId": 53,
    "GetProcessIdOfThread": 54, "GetThreadId": 55, "GetResourceLimit": 56,
    "GetResourceLimitLimitValues": 57, "GetResourceLimitCurrentValues": 58, "GetThreadContext": 59,
    "Break": 60, "OutputDebugString": 61,
    # ndsp (DSP_FlushDataCache) などが使う
    "InvalidateProcessDataCache": 82, "StoreProcessDataCache": 83, "FlushProcessDataCache": 84,
    "StartInterProcessDma": 85, "StopDma": 86, "GetDmaState": 87, "RestartDma": 88,
    "SignalAndWait": 38,
}
_SYSCALL_LINES = "\n".join(f"    {name}: {num}" for name, num in _SYSCALLS.items())

RSF_TEMPLATE = """\
BasicInfo:
  Title                   : "{title}"
  CompanyCode             : "00"
  ProductCode             : "{product_code}"
  ContentType             : Application
  Logo                    : Nintendo

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
    - CategorySystemApplication
    - CategoryHardwareCheck
    - CategoryFileSystemTool
    - Debug
    - TwlCardBackup
    - TwlNandData
    - Boss
    - DirectSdmc
    - Core
    - CtrNandRo
    - CtrNandRw
    - CtrNandRoWrite
    - CategorySystemSettings
    - CardBoard
    - ExportImportIvs
    - DirectSdmcWrite
    - SwitchCleanup
    - SaveDataMove
    - Shop
    - Shell
    - CategoryHomeMenu
  MemoryType              : Application
  SystemMode              : 64MB
  IdealProcessor          : 0
  AffinityMask            : 1
  Priority                : 16
  MaxCpu                  : 0x9E
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
  SystemModeExt           : Legacy
  CpuSpeed                : 804MHz
  EnableL2Cache           : true
  CanAccessCore2          : true
  IORegisterMapping:
    - 1ff00000-1ff7ffff
  MemoryMapping:
    - 1f000000-1f5fffff:r
  SystemCallAccess:
{syscalls}
  ServiceAccessControl:
    - APT:U
    - $hioFIO
    - $hostio0
    - $hostio1
    - ac:u
    - am:net
    - boss:U
    - cam:u
    - cecd:u
    - cfg:nor
    - cfg:u
    - csnd:SND
    - dsp::DSP
    - frd:u
    - fs:USER
    - gsp::Gpu
    - gsp::Lcd
    - hid:USER
    - http:C
    - ir:rst
    - ir:u
    - ir:USER
    - mic:u
    - ndm:u
    - news:s
    - nwm::EXT
    - nwm::UDS
    - ptm:sysm
    - ptm:u
    - pxi:dev
    - soc:U
    - ssl:C
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
            syscalls=_SYSCALL_LINES,
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
            "-romfs", romfs_bin, "-exefslogo", "-target", "t",
            "-major", str(major), "-minor", str(minor), "-micro", str(micro),
        ],
        log,
    )
    return dst
