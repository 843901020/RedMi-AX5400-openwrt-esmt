# 红米 AX5400 (RA74 / IPQ5018) 刷 OpenWrt 踩坑全记录

> 一台"无限重启的砖"，如何在**不重新编译固件**的前提下装上 OpenWrt。
>
> **核心发现：同一个型号的 AX5400 用了两种不同的 NAND 芯片。**
> OpenWrt 的设备树把 `nand-ecc-strength` 硬编码成 `<8>`，只适配其中一种（OOB 128 的
> GigaDevice），另一种（OOB 64 的 ESMT）装上去必然变砖 —— 而且 `sysupgrade` 会**报告成功**。
>
> 本文给出：完整的根因分析、三组对照实验、以及一套**二进制打补丁**的解法。

---

## 目录

- [1. 现象：无限重启](#1-现象无限重启)
- [2. 关键发现：两种 NAND 芯片](#2-关键发现两种-nand-芯片)
- [3. 为什么两种芯片会导致完全不同的结果](#3-为什么两种芯片会导致完全不同的结果)
- [4. 三组对照实验（决定性证据）](#4-三组对照实验决定性证据)
- [5. 为什么 sysupgrade 会"假成功"](#5-为什么-sysupgrade-会假成功)
- [6. 解法：不编译，直接改固件二进制](#6-解法不编译直接改固件二进制)
- [7. 完整刷机流程](#7-完整刷机流程)
- [8. 救砖兜底：官方恢复模式](#8-救砖兜底官方恢复模式)
- [9. 没有 WAN 口时如何装软件包](#9-没有-wan-口时如何装软件包)
- [10. 分区表（附一个致命陷阱）](#10-分区表附一个致命陷阱)
- [11. 工具清单](#11-工具清单)
- [12. 常见问题](#12-常见问题)

---

## 1. 现象：无限重启

串口（115200 8N1，板载 TTL）看到：

```
### main_loop: bootcmd="bootmiwifi"
Hit any key to stop autoboot:  0
boot from rootfs 1
miwifi: check crash in rmem !
ubi0: attaching mtd1
ubi0: scanning is finished
UBI init error 22
Erasing NAND...
Erasing at 0x480000 --  25% ... 100% complete.
Writing to NAND... OK
resetting ...
```

约 9~11 秒一轮，永远起不来。

**关键判断：不是硬件损坏。** 依据：

- `SBL1` / `DDR sanity test` / `QSEE` / `DEVCFG` / `APPSBL` 全部加载正常
- `nand bad` 无坏块
- `NAND: 128 MiB` 容量识别正确
- U-Boot 本身能跑、能响应按键、能写 NAND

所以问题在 **rootfs 分区的内容**，不在芯片本身。

---

## 2. 关键发现：两种 NAND 芯片

### 2.1 怎么发现的

一开始我把问题归因为"OpenWrt 固件有 bug"，试了三个不同构建、重刷了十几次，
每次都卡在同一个地方：`ubi0: attaching mtd18` 报 ECC 错误。

转折点是：**手上有另一台能正常跑 OpenWrt 的同型号 RA74**。
把两台的关键信息一对比，发现了决定性差异 —— **NAND 芯片根本不一样。**

### 2.2 两台机器的对照

| | **故障机** | **正常机** |
|---|---|---|
| 型号 | Redmi AX5400 (RA74) | Redmi AX5400 (RA74) |
| SoC | IPQ5018 | IPQ5018 |
| 序列号 | `30473/A2PC05950` | `30473/A2PA16225` |
| 板名 | `Redmi_B0BB` | `Redmi_7D4B` |
| **NAND 厂商** | **ESMT** | **GigaDevice** |
| **NAND 型号** | **F50D1G41LB(2M)** | （未打印具体型号） |
| **OOB / Spare** | **64 字节** | **128 字节** |
| U-Boot 报的 ECC | `ECC: 4-bit` | （未打印） |
| 容量 | 128 MiB | 128 MiB |
| 页大小 | 2048 | 2048 |
| 块大小 | 128 KiB | 128 KiB |

### 2.3 原始日志（U-Boot 侧）

**故障机：**

```
NAND:  QPIC controller support serial NAND
ID = 7f7f11c8
Vendor = c8
Device = 11
Serial Nand Device Found With ID : 0xc8 0x11
Serial NAND device Manufature:F50D1G41LB(2M)
Device Size:128 MiB, Page size:2048, Spare Size:64, ECC:4-bit
ESMT F50D1G41LB(2M), disable serial training.
Error in serial training.
switch back to 50MHz with feed back clock bit enabled
```

注意 `Spare Size:64` 和 `ECC:4-bit`。

**正常机（从运行中的 OpenWrt 里读 dmesg）：**

```
spi-nand spi0.0: GigaDevice SPI NAND was found.
spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 128
qcom_snand 79b0000.spi: Warning: due to hw limitation, the reported number of
                         the corrected bits may be inaccurate
```

注意 `OOB size: 128`。

### 2.4 原始日志（内核侧）

**故障机跑 OpenWrt 时：**

```
spi-nand spi0.0: ESMT SPI NAND was found.
spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 64
[    2.841797] ubi0 warning: ubi_io_read: error -74 (ECC error) while reading
                          64 bytes from PEB 0:0, read only 64 bytes, retry
[    2.878146] ubi0 warning: ubi_io_read: error -74 (ECC error) while reading
                          64 bytes from PEB 0:2048, read only 64 bytes, retry
```

芯片识别是对的（OOB 64），但 **ECC 强度来自设备树（8-bit）**，于是读写全错。

---

## 3. 为什么两种芯片会导致完全不同的结果

### 3.1 OOB 决定 ECC 上限

OOB（Out-Of-Band，也叫 Spare Area）是每页旁边那块额外空间，专门放 ECC 校验码。

对于 2048 字节页、512 字节 ECC 步长：

| ECC 强度 | 每步长开销 | 每页总开销（8 步长） | OOB 64 | OOB 128 |
|---|---|---|---|---|
| 4-bit | 7 B | 8 × 7 = **56 B** | ✅ | ✅ |
| 8-bit | 14 B | 8 × 14 = **112 B** | ❌ 放不下 | ✅ |
| 12-bit | 21 B | 8 × 21 = 168 B | ❌ | ❌ |

**结论：OOB 64 的芯片最多只能上 4-bit ECC，8-bit 的校验码放不下。**

### 3.2 而 OpenWrt 写死了 8-bit

从 `squashfs-sysupgrade.bin` 的 `kernel`（FIT）里解析出的内嵌 DTB：

```
/soc@0/spi@79b0000
    compatible = 'qcom,ipq5018-snand'

/soc@0/spi@79b0000/nand@0
    compatible          = 'spi-nand'
    nand-ecc-engine     = 47
    nand-ecc-step-size  = 512
    nand-ecc-strength   = 8        ← 问题所在，写死的
```

### 3.3 于是两台机器的命运完全不同

**正常机（GigaDevice / OOB 128）：**

```
OpenWrt 用 8-bit 写 → 校验码 112 B ≤ 128 B OOB   ✅ 放得下
U-Boot 读          → 芯片工作在 8-bit 模式        ✅ 读得出来
```

**故障机（ESMT / OOB 64）：**

```
OpenWrt 用 8-bit 写 → 校验码 112 B > 64 B OOB    ❌ 放不下
                     ↓
                写进去的数据结构是坏的
                     ↓
U-Boot 用 4-bit 读 → ECC 校验失败                ❌ 读不出来
                     ↓
                读不出内核 → 无限重启
```

---

## 4. 三组对照实验（决定性证据）

为了确认"是 ECC 强度不兼容"而不是别的，我做了三组交叉实验：

| 谁写的 | 用的 ECC | U-Boot 能读 | OpenWrt 能读 |
|---|---|---|---|
| **U-Boot**（`nand write`） | 4-bit | ✅ | ❌ ECC error |
| **OpenWrt**（`sysupgrade`） | 8-bit | ❌ ECC error | ✅ |
| **原厂内核**（`mtd write`） | 4-bit | ✅ | ✅ |

### 这组数据的含义

1. **前两行互斥** —— U-Boot 和 OpenWrt 各写各的，互相读不了。这就是死结。
2. **第三行两边通吃** —— 原厂内核和 U-Boot 都是 4-bit，所以它们之间没问题。
3. 说明 **U-Boot 固定 4-bit**（跟着芯片自动选），而 **OpenWrt 固定 8-bit**（跟着 DTB）。

### 具体实验过程

**实验一：U-Boot 写 → OpenWrt 读**

用 U-Boot 把原厂 rootfs 写回 mtd18/mtd19，然后跑 OpenWrt initramfs：

```
ubi0: attaching mtd18
ubi0 warning: ubi_io_read: error -74 (ECC error) while reading 64 bytes from PEB 0:0
ubi0 error: ubi_io_read: error -74 (ECC error) ... read 64 bytes
```
→ **失败**，整个分区每个 PEB 都读不出来。

**实验二：OpenWrt 写 → U-Boot 读**

`sysupgrade` 报告 `successful`，卷都建好了，然后重启：

```
boot from rootfs 0
miwifi: check crash in rmem !
ubi0: attaching mtd1
ECC 错误地址: 0xa80000 ~ 0x1500000      ← mtd18 开头 13MB 全读不了
```
→ **失败**，U-Boot 读不出内核。

**实验三：原厂内核写 → 双方都能读**

从原厂固件 SSH 进去，用 `mtd -e <分区> write <文件> <分区>` 写入：

```
U-Boot 读 → ✅ 正常启动
OpenWrt 读 → ✅ 只报 image_seq 不匹配（那是残留数据问题，不是 ECC）
```

**这个实验直接证明了：只有原厂内核写的 4-bit 数据是两边通用的。**

---

## 5. 为什么 sysupgrade 会"假成功"

这是最坑的地方。`sysupgrade` 的输出看起来完全正常：

```
ubi0: attaching mtd18
ubi0: empty MTD device detected
ubi0: attached mtd18 (name "ubi_kernel", size 36 MiB)
ubi1: attaching mtd19
ubi1: empty MTD device detected
ubi1: attached mtd19 (name "rootfs", size 81 MiB)
Volume ID 127 ... name "provisioning"
Volume ID 0, size 49 LEBs ... name "kernel"
Volume ID 0, size 70 LEBs ... name "rootfs"
Volume ID 1, size 556 LEBs ... name "rootfs_data"
sysupgrade successful
```

**它确实成功了** —— 分区挂对了、卷建对了、数据写对了。

**但它写出来的东西，唯一能启动它的 U-Boot 读不了。**

因为 `sysupgrade` 用的是 initramfs 里的 **OpenWrt 内核**（8-bit ECC），
而重启后负责读内核的是 **U-Boot**（4-bit ECC）。

这是个"自己验自己"的陷阱：sysupgrade 用自己的内核写、用自己的内核验证，当然全过。
真正要读它的是另一个程序（U-Boot），而那个程序读不了。

---

## 6. 解法：不编译，直接改固件二进制

### 6.1 思路

既然问题出在 DTB 里的一个 u32 值（`8` → `4`），而它在固件镜像里就是个字节，
那**直接改二进制**就行 —— 不需要 Linux 编译环境、不需要 30GB 磁盘、不需要等 3 小时编译。

### 6.2 为什么可以原地改（关键技术点）

| 结构 | 结论 |
|---|---|
| UBI **内核卷是动态卷**（`vol_type=1`） | `data_size` / `data_crc` 均为 0，**改数据区不需要重算 UBI CRC** |
| UBI `hdr_crc` | 只覆盖 64 字节 VID 头，不动头就不用改 |
| FIT 哈希节点 | `/images/fdt-1/hash-1`(crc32) + `hash-2`(sha1)，**必须重算** |
| sysupgrade 尾部元数据 | 512 对齐后追加 281 字节 JSON（含 `FWx0` 魔数 + CRC + 长度），**重打包 tar 会丢** |

### 6.3 两个工具

```bash
# 改 UBI 镜像里的内核 FIT（initramfs-factory.ubi 这类）
python tools/_ubipatch.py <in.ubi> <out.ubi> 4

# 改裸 FIT（如果直接拿到的是 FIT）
python tools/_fitpatch.py <in.bin> <out.bin> 4
```

两者都会：找到 `flat_dt` 子镜像 → 把 `nand-ecc-strength` 改成 4 → 重算 crc32 + sha1 → 写回。
**文件大小不变**，所以不影响任何偏移。

### 6.4 sysupgrade.bin 的特殊处理

`sysupgrade.bin` 是 tar + 尾部元数据，**不能重新打包**（会丢元数据）：

```python
import tarfile
d = bytearray(open(src, 'rb').read())
m = [x for x in tarfile.open(src).getmembers() if x.name.endswith('/kernel')][0]
d[m.offset_data:m.offset_data + m.size] = patched_kernel   # 等长覆写，其余字节不动
open(dst, 'wb').write(d)
```

即使元数据完整，`sysupgrade` 仍可能误报 `Image metadata not present`，
用 **`sysupgrade -n -F`** 强制刷入即可。

### 6.5 补丁效果

| 指标 | 补丁前 | 补丁后 |
|---|---|---|
| initramfs 启动时的 ECC 报错行数 | **906 行** | **0 行** |
| `nand-ecc-strength` | 8 | 4 |
| fdt crc32 | （旧值） | `0xc0eb1050` |
| fdt sha1 | （旧值） | `8eef57820bf27220c4e1bddfcf84a4f974a96094` |

**ECC 报错从 906 行降到 0 行** —— 这是补丁生效最直接的标志。

---

## 7. 完整刷机流程

### 7.1 准备两个补丁镜像

```bash
python tools/_ubipatch.py openwrt-...-initramfs-factory.ubi initramfs_p4.ubi 4
# 再用 tarfile 原地覆写 sysupgrade 的 kernel -> sysupgrade_p4.bin
```

### 7.2 进入 U-Boot

- **`bootdelay` > 0**：直接连发回车即可中断（`tools/_uboot_stop.py`）
- **`bootdelay` = 0**：**先按住 Reset，再插电源，按住 20 秒**
  （U-Boot 检测到按键后还要**再确认 5 秒**，按 12 秒不够）
  日志出现 `detect button pressed 5 secs !` 才算成功

> 如果进了恢复模式（`cmd=dhcp`）但想回 U-Boot 提示符，用 `tools/_abort.py` 连发 Ctrl-C。

### 7.3 刷入补丁版 initramfs

```
setenv ipaddr 192.168.31.1
setenv netmask 255.255.255.0
setenv serverip 192.168.31.100
tftpboot 0x44000000 initramfs_p4.ubi
crc32 0x44000000 0xF80000
nand erase 0x2E80000 0x2400000
nand write 0x44000000 0x2E80000 0xF80000
reset
```

电脑端跑 TFTP 服务器：`python tools/_tftp.py <目录>`

### 7.4 进 initramfs 后（关键）

```sh
mtd erase ubi_kernel      # mtd18
mtd erase rootfs          # mtd19
wget -O /tmp/fw.bin http://<PC_IP>:8000/sysupgrade_p4.bin
sysupgrade -n -F /tmp/fw.bin
```

> **擦空是必须的。** `sysupgrade` 第一步是 `ubiattach`，分区里有旧数据（ECC 不兼容）
> 会直接报错中止，根本走不到格式化。擦空后日志出现
> `empty MTD device detected` 才会继续。

### 7.5 修启动标志

`sysupgrade` 内部的 `fw_setenv flag_boot_rootfs 0` 会失败
（日志里 `Warning: Bad CRC, using default environment`），必须在 U-Boot 里补：

```
setenv flag_boot_rootfs 0
setenv flag_last_success 0
setenv flag_boot_success 1
setenv flag_try_sys1_failed 0
setenv flag_try_sys2_failed 0
saveenv
reset
```

### 7.6 成功标志

```
$ mount | head -1
/dev/root on /rom type squashfs (ro,relatime,errors=continue)     ← 不是 tmpfs

$ df -h | grep -E 'rom|overlay'
/dev/root    8.5M  8.5M  0  100%  /rom
/dev/ubi0_1  60.4M 72.0K 57.2M  0%  /overlay
overlayfs:/overlay  60.4M 72.0K 57.2M 0%  /

$ ubus call system board
{
  "kernel": "6.18.60",
  "model": "Xiaomi Redmi AX5400",
  "board_name": "xiaomi,redmi-ax5400",
  "rootfs_type": "squashfs"
}

$ fw_printenv flag_boot_rootfs
flag_boot_rootfs=0

$ iwinfo
phy0-ap0  ESSID: "OpenWrt"  Channel: 1  (2.412 GHz)  HE20
phy1-ap0  ESSID: "OpenWrt"  Channel: 36 (5.180 GHz)  HE80
```

---

## 8. 救砖兜底：官方恢复模式

任何一步失败都能用这个回到原厂：

1. 电脑以太网设静态 `192.168.31.100/24`，**不设网关**
   （设了网关会抢默认路由，导致电脑断网）
2. `python tools/_recovery.py <官方固件.bin>`
   （DHCP:67 + TFTP:69，option 66/67 都填）
3. 路由器：按住 Reset → 插电 → 按 20 秒 → 松开
4. 它会自己 `ping` → `dhcp` → `tftp` → `xq_flash_erase` → `Upgrade success!`

> `Trying to ping server.....` 会看起来卡住很久，**其实后面会悄悄走通，别急着 Ctrl-C**。
> 中途打断会导致 `dhcp failed, retry` 反复重试。

刷完可能卡住（串口无声、网口有 link 但不发包），**再断一次电**即可正常启动。

---

## 9. 没有 WAN 口时如何装软件包

路由器没有默认路由（WAN 未接），但电脑能上网。在电脑上跑反向代理，
把路由器的 apk 请求转发到 downloads.openwrt.org：

```bash
python tools/_apkproxy.py 8000
```

```sh
# 路由器上
sed -i 's|https://downloads.openwrt.org|http://<PC_IP>:8000|g' \
    /etc/apk/repositories.d/distfeeds.list
apk update        # OK: 11312 distinct packages available
apk add <pkg>
```

> ⚠️ **注意版本匹配**：snapshot 是滚动更新的，旧固件装新包会出问题。
> 实测 `apk add luci` 能装成功，但 `/cgi-bin/luci/` 返回 403 ——
> 因为 LuCI 在这两个版本之间从 **Lua 迁到了 ucode**，接口对不上。
> 想要 Web 界面，建议直接用**自带 LuCI 的稳定版镜像**（如 24.10.x）再打 ECC 补丁。

---

## 10. 分区表（附一个致命陷阱）

### 10.1 `smeminfo` 读出的真实值

| 分区 | 偏移 | 大小 |
|---|---|---|
| `0:SBL1` | `0x0000000` | `0x80000` |
| `0:MIBIB` | `0x0080000` | `0x80000` |
| `0:BOOTCONFIG` | `0x0100000` | `0x40000` |
| `0:QSEE` | `0x0180000` | `0x100000` |
| `0:DEVCFG` | `0x0380000` | `0x40000` |
| `0:CDT` | `0x0400000` | `0x40000` |
| `0:APPSBLENV` | `0x0480000` | `0x80000` |
| `0:APPSBL` | `0x0500000` | `0x140000` |
| `0:ART` | `0x0780000` | `0x100000` |
| `0:TRAINING` | `0x0880000` | `0x80000` |
| `bdata` | `0x0900000` | `0x80000` |
| `crash` | `0x0980000` | `0x80000` |
| **`crash_syslog`** | **`0x0A00000`** | **`0x80000`** |
| `rootfs` | `0x0A80000` | `0x2400000` |
| `rootfs_1` | `0x2E80000` | `0x2400000` |
| `overlay` | `0x5280000` | `0x1F00000` |

### 10.2 ⚠️ 致命陷阱

**不要用 `/proc/mtd` 累加推算偏移！**

我一开始就是这么算的，结果漏掉了 `crash_syslog`（`0xA00000`，`0x80000`），
导致 `rootfs` 的偏移算成 `0xAA0000` 而不是 `0xA80000` —— **正好错 512KB**。

写进去的数据完全错位，刷完还是砖，而且看起来像"固件有问题"。

**一定要用 `smeminfo` 读真实偏移**（U-Boot 里执行 `smeminfo`）。

### 10.3 OpenWrt 的分区重映射

OpenWrt 的 DTS 会重新划分：

| OpenWrt 分区名 | 偏移 | 大小 |
|---|---|---|
| `ubi_kernel` | `0xA80000` | 36 MiB |
| `rootfs` | `0x2E80000` | 81.5 MiB（到 NAND 末尾） |

内核 cmdline：`ubi.mtd=rootfs root=/dev/ubiblock0_0`

→ **内核在 mtd18（`ubi_kernel`），rootfs 在 mtd19（`rootfs`），`flag_boot_rootfs=0`**

这和 `platform.sh` 里的定义一致：

```sh
xiaomi,redmi-ax5400)
    fw_setenv flag_boot_rootfs 0
    fw_setenv flag_last_success 0
    fw_setenv flag_boot_success 1
    fw_setenv flag_try_sys1_failed 8
    fw_setenv flag_try_sys2_failed 8
    CI_KERN_UBIPART="ubi_kernel"     # 内核
    CI_ROOT_UBIPART="rootfs"         # rootfs
    CI_DATA_UBIPART="rootfs"
    nand_do_upgrade "$1"
```

---

## 11. 工具清单

| 工具 | 用途 |
|---|---|
| `_ubipatch.py` | 给 UBI 镜像里的内核 FIT 打 ECC 补丁（**核心**） |
| `_fitpatch.py` | 给裸 FIT 打 ECC 补丁 |
| `_ghpush.py` | 通过 GitHub API 提交（`git push` 走不通时用） |
| `_apkproxy.py` | 反向代理，让无 WAN 的路由器通过电脑装包 |
| `_recovery.py` | 小米官方恢复模式喂固件（DHCP + TFTP） |
| `_tftp.py` | 通用 TFTP 服务器（U-Boot 拉文件用） |
| `_ub.py` | 串口执行 U-Boot 命令 |
| `_sh.py` | 串口执行 Linux shell 命令 |
| `_boot.py` | 发 reset 并记录启动日志 |
| `_watch.py` | 串口监听（自动过滤 ECC 噪声） |
| `_abort.py` | Ctrl-C 连发，从恢复模式抢 U-Boot 提示符 |
| `_uboot_stop.py` | 连发回车，在 bootdelay 窗口内中断自动启动 |
| `_uart.py` | 串口抓包 / 发送 / 交互 |
| `_owrt.py` | SSH 执行命令（paramiko） |

依赖：

```bash
pip install pyserial paramiko
```

---

## 12. 常见问题

**Q: 怎么判断我手上的 RA74 是哪种芯片？**

看 U-Boot 启动日志（串口）：

```
Serial NAND device Manufature:F50D1G41LB(2M)
Device Size:128 MiB, Page size:2048, Spare Size:64, ECC:4-bit
                                            ^^^^^^^^^^^^^^ OOB 64 → 需要打补丁
```

或者从运行中的 OpenWrt：`dmesg | grep -i "OOB size"`
- `OOB size: 64` → **ESMT 芯片，必须打补丁**
- `OOB size: 128` → GigaDevice，原版固件直接可用

**Q: 打了补丁之后，还能用原厂固件吗？**

可以。补丁只改 OpenWrt 镜像里的 DTB，不影响 U-Boot 和原厂固件。
想回原厂随时走恢复模式。

**Q: 为什么不直接改 U-Boot 的 ECC？**

U-Boot 的 ECC 是跟着芯片自动选的（OOB 64 → 4-bit），已经是对的。
错的是 OpenWrt 那侧写死的 8-bit。

**Q: 为什么不用 ImageBuilder 重新打包？**

ImageBuilder 不能改 DTS/DTB，只能选包。要改 ECC 必须动设备树，得用完整 buildroot 编译 ——
而本文的方案连编译都不需要。

---

## 13. 免责声明

刷机有风险。本文流程已在 **RA74 / ESMT F50D1G41LB / OOB 64** 上验证通过，
但不同批次硬件可能仍有差异。

**操作前务必备份全部分区**（`dd if=/dev/mtdN of=...`），并确认手上有可用的官方固件用于恢复。
