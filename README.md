# 红米 AX5400 (RA74 / IPQ5018) 刷 OpenWrt 全记录

> 从"无限重启的砖"到"跑着 OpenWrt + LuCI 的可用路由器"的完整过程。
>
> **核心发现：同一个型号的 AX5400 用了两种不同的 NAND 芯片。**
> OpenWrt 的设备树把 `nand-ecc-strength` 硬编码成 `<8>`，只适配 OOB 128 的 GigaDevice，
> 另一种 OOB 64 的 ESMT 装上去必然变砖 —— 而且 `sysupgrade` 会**报告成功**。
>
> 本文给出：完整根因分析、三组对照实验、**不用编译的二进制打补丁方案**、
> 以及从零到 LuCI 可用的**全流程操作步骤**和**踩坑清单**。

---

## 目录

- [1. 最终成果](#1-最终成果)
- [2. 现象：无限重启](#2-现象无限重启)
- [3. 关键发现：两种 NAND 芯片](#3-关键发现两种-nand-芯片)
- [4. 为什么两种芯片结果完全不同](#4-为什么两种芯片结果完全不同)
- [5. 三组对照实验（决定性证据）](#5-三组对照实验决定性证据)
- [6. 为什么 sysupgrade 会"假成功"](#6-为什么-sysupgrade-会假成功)
- [7. 解法：不编译，直接改固件二进制](#7-解法不编译直接改固件二进制)
- [8. 完整刷机流程（从砖到 OpenWrt + LuCI）](#8-完整刷机流程从砖到-openwrt--luci)
- [9. 救砖兜底：官方恢复模式](#9-救砖兜底官方恢复模式)
- [10. 分区表（附一个致命陷阱）](#10-分区表附一个致命陷阱)
- [11. 踩坑清单（速查）](#11-踩坑清单速查)
- [12. 工具清单](#12-工具清单)
- [13. 常见问题](#13-常见问题)

---

## 1. 最终成果

```
OpenWrt SNAPSHOT r38209-ada52cc7ed
kernel 6.18.60 · squashfs + overlay 60.4MB
192.168.1.1 · SSH root/root · LuCI 正常
WiFi: OpenWrt (2.4G ch1 HE20) / OpenWrt (5G ch36 HE80)
```

硬件：Redmi AX5400 (RA74 / IPQ5018 / ESMT F50D1G41LB / OOB 64)

---

## 2. 现象：无限重启

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

## 3. 关键发现：两种 NAND 芯片

### 3.1 怎么发现的

一开始我把问题归因为"OpenWrt 固件有 bug"，试了三个不同构建、重刷了十几次，
每次都卡在同一个地方：`ubi0: attaching mtd18` 报 ECC 错误。

转折点是：**手上有另一台能正常跑 OpenWrt 的同型号 RA74**。
把两台的关键信息一对比，发现了决定性差异 —— **NAND 芯片根本不一样。**

### 3.2 两台机器的对照

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
| 容量 / 页 / 块 | 128 MiB / 2048 / 128 KiB | 128 MiB / 2048 / 128 KiB |

### 3.3 原始日志（U-Boot 侧）

**故障机：**

```
NAND:  QPIC controller support serial NAND
Serial NAND device Manufature:F50D1G41LB(2M)
Device Size:128 MiB, Page size:2048, Spare Size:64, ECC:4-bit
ESMT F50D1G41LB(2M), disable serial training.
```

注意 `Spare Size:64` 和 `ECC:4-bit`。

**正常机（从运行中的 OpenWrt 里读 dmesg）：**

```
spi-nand spi0.0: GigaDevice SPI NAND was found.
spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 128
```

注意 `OOB size: 128`。

### 3.4 原始日志（内核侧）

**故障机跑 OpenWrt 时：**

```
spi-nand spi0.0: ESMT SPI NAND was found.
spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 64
[    2.841797] ubi0 warning: ubi_io_read: error -74 (ECC error) while reading
                          64 bytes from PEB 0:0, read only 64 bytes, retry
```

芯片识别是对的（OOB 64），但 **ECC 强度来自设备树（8-bit）**，于是读写全错。

---

## 4. 为什么两种芯片结果完全不同

### 4.1 OOB 决定 ECC 上限

OOB（Out-Of-Band，也叫 Spare Area）是每页旁边那块额外空间，专门放 ECC 校验码。

对于 2048 字节页、512 字节 ECC 步长：

| ECC 强度 | 每步长开销 | 每页总开销（8 步长） | OOB 64 | OOB 128 |
|---|---|---|---|---|
| 4-bit | 7 B | 8 × 7 = **56 B** | ✅ | ✅ |
| 8-bit | 14 B | 8 × 14 = **112 B** | ❌ 放不下 | ✅ |
| 12-bit | 21 B | 8 × 21 = 168 B | ❌ | ❌ |

**结论：OOB 64 的芯片最多只能上 4-bit ECC。**

### 4.2 而 OpenWrt 写死了 8-bit

从固件的 `kernel`（FIT）里解析出的内嵌 DTB：

```
/soc@0/spi@79b0000
    compatible = 'qcom,ipq5018-snand'

/soc@0/spi@79b0000/nand@0
    compatible          = 'spi-nand'
    nand-ecc-engine     = 47
    nand-ecc-step-size  = 512
    nand-ecc-strength   = 8        ← 问题所在，写死的
```

### 4.3 两台机器的命运

**正常机（GigaDevice / OOB 128）：**

```
OpenWrt 用 8-bit 写 → 校验码 112 B ≤ 128 B OOB   ✅
U-Boot 读          → 芯片工作在 8-bit 模式        ✅
```

**故障机（ESMT / OOB 64）：**

```
OpenWrt 用 8-bit 写 → 校验码 112 B > 64 B OOB    ❌ 放不下
                     ↓
                写进去的数据结构是坏的
                     ↓
U-Boot 用 4-bit 读 → ECC 校验失败                ❌ 读不出内核
                     ↓
                无限重启
```

---

## 5. 三组对照实验（决定性证据）

| 谁写的 | 用的 ECC | U-Boot 能读 | OpenWrt 能读 |
|---|---|---|---|
| **U-Boot**（`nand write`） | 4-bit | ✅ | ❌ ECC error |
| **OpenWrt**（`sysupgrade`） | 8-bit | ❌ ECC error | ✅ |
| **原厂内核**（`mtd write`） | 4-bit | ✅ | ✅ |

**含义：**

1. **前两行互斥** —— U-Boot 和 OpenWrt 各写各的，互相读不了。这就是死结。
2. **第三行两边通吃** —— 原厂内核和 U-Boot 都是 4-bit，所以它们之间没问题。
3. 说明 **U-Boot 固定 4-bit**（跟着芯片自动选），**OpenWrt 固定 8-bit**（跟着 DTB）。

**具体实验：**

- **U-Boot 写 → OpenWrt 读**：整个分区每个 PEB 都 `error -74 (ECC error)`
- **OpenWrt 写 → U-Boot 读**：`boot from rootfs 0` 后 ECC 错误地址铺满 `0xa80000 ~ 0x1500000`
- **原厂内核写 → 双方都能读**：U-Boot 正常启动，OpenWrt 只报 `image_seq` 不匹配（残留数据问题，不是 ECC）

---

## 6. 为什么 sysupgrade 会"假成功"

```
ubi0: attaching mtd18
ubi0: empty MTD device detected
ubi0: attached mtd18 (name "ubi_kernel", size 36 MiB)
ubi1: attaching mtd19
ubi1: empty MTD device detected
ubi1: attached mtd19 (name "rootfs", size 81 MiB)
Volume ID 0, size 49 LEBs ... name "kernel"
Volume ID 0, size 70 LEBs ... name "rootfs"
Volume ID 1, size 556 LEBs ... name "rootfs_data"
sysupgrade successful
```

**它确实成功了** —— 分区挂对了、卷建对了、数据写对了。

**但它写出来的东西，唯一能启动它的 U-Boot 读不了。**

因为 `sysupgrade` 用的是 initramfs 里的 **OpenWrt 内核**（8-bit ECC），
而重启后负责读内核的是 **U-Boot**（4-bit ECC）。

**这是个"自己验自己"的陷阱**：写和验证用同一个内核，当然全过；
真正要读它的是另一个程序，而那个程序读不了。

---

## 7. 解法：不编译，直接改固件二进制

### 7.1 思路

问题只是 DTB 里的一个 u32 值（`8` → `4`），它在固件镜像里就是个字节。
**直接改二进制** —— 不需要 Linux 编译环境、不需要 30GB 磁盘、不需要等 3 小时。

### 7.2 为什么可以原地改

| 结构 | 结论 |
|---|---|
| UBI **内核卷是动态卷**（`vol_type=1`） | `data_size` / `data_crc` 均为 0，**改数据区不需要重算 UBI CRC** |
| UBI `hdr_crc` | 只覆盖 64 字节 VID 头，不动头就不用改 |
| FIT 哈希节点 | `/images/fdt-1/hash-1`(crc32) + `hash-2`(sha1)，**必须重算** |
| sysupgrade 尾部元数据 | 512 对齐后追加 281 字节 JSON（含 `FWx0` 魔数），**重打包 tar 会丢** |

### 7.3 两个工具

```bash
# 改 UBI 镜像里的内核 FIT（initramfs-factory.ubi 这类）
python tools/_ubipatch.py <in.ubi> <out.ubi> 4

# 改裸 FIT
python tools/_fitpatch.py <in.bin> <out.bin> 4
```

两者都会：找 `flat_dt` 子镜像 → 改 `nand-ecc-strength` 为 4 → 重算 crc32 + sha1 → 写回。
**文件大小不变**，不影响任何偏移。

### 7.4 sysupgrade.bin 的特殊处理

它是 tar + 尾部元数据，**不能重新打包**（会丢元数据）：

```python
import tarfile
d = bytearray(open(src, 'rb').read())
m = [x for x in tarfile.open(src).getmembers() if x.name.endswith('/kernel')][0]
d[m.offset_data:m.offset_data + m.size] = patched_kernel   # 等长覆写
open(dst, 'wb').write(d)
```

即使元数据完整，`sysupgrade` 仍可能误报 `Image metadata not present`，
用 **`sysupgrade -n -F`** 强制刷入。

### 7.5 补丁效果

| 指标 | 补丁前 | 补丁后 |
|---|---|---|
| initramfs 启动时 ECC 报错行数 | **906 行** | **0 行** |
| `nand-ecc-strength` | 8 | 4 |
| fdt crc32 | （旧值） | `0xc0eb1050` |
| fdt sha1 | （旧值） | `8eef57820bf27220c4e1bddfcf84a4f974a96094` |

补丁只改动 **25 个字节**（1 个 ECC 值 + 4 字节 crc32 + 20 字节 sha1）。

---

## 8. 完整刷机流程（从砖到 OpenWrt + LuCI）

### 8.1 准备

**电脑侧：**

- TTL 转 USB 接路由器（115200 8N1）
- 网线接路由器 LAN 口
- 以太网设静态 `192.168.31.100/24`（**不设网关**，否则抢默认路由导致断网）
- 关掉防火墙（或放行 UDP 67/69、TCP 80/8000、ICMP）

**镜像：**

```bash
python tools/_ubipatch.py openwrt-...-initramfs-factory.ubi initramfs_p4.ubi 4
# sysupgrade 用 tarfile 等长覆写内核 -> sysupgrade_p4.bin
```

### 8.2 进 U-Boot

三种方式，按可用性选：

| 方式 | 条件 | 操作 |
|---|---|---|
| **敲键中断** | `bootdelay` > 0 | 连发回车（`tools/_uboot_stop.py`） |
| **按住 Reset** | `bootdelay` = 0 | 按住 Reset → 插电 → **按 20 秒** → 松开 |
| **从系统内设** | 系统能跑 | `fw_setenv bootdelay 5` 后重启 |

> ⚠️ **按 12 秒不够！** U-Boot 检测到按键后还要**再确认 5 秒**，
> 日志出现 `detect button pressed 5 secs !` 才算成功。
>
> 如果误进恢复模式（`cmd=dhcp`），用 `tools/_abort.py` 连发 Ctrl-C 抢回提示符。

### 8.3 刷 initramfs —— **写到 mtd18（槽 0）**

```
setenv ipaddr 192.168.31.1
setenv netmask 255.255.255.0
setenv serverip 192.168.31.100
tftpboot 0x44000000 initramfs_p4.ubi
crc32 0x44000000 0xF80000
nand erase 0xA80000 0x2400000
nand write 0x44000000 0xA80000 0xF80000
reset
```

> **⚠️ 为什么写 mtd18 而不是 mtd19？**
>
> `bootmiwifi` 每次启动会**重写 env 并翻转 `flag_boot_rootfs`**，
> 手动设成 1 也会被覆盖回 0。
> **写到槽 0（mtd18）就完全绕开了标志位问题** —— 不管标志是几都会启动它。
>
> 这是本次最关键的一个技巧，之前反复失败就是卡在这里。

### 8.4 进 initramfs 后刷 sysupgrade

```sh
mtd erase ubi_kernel      # mtd18
mtd erase rootfs          # mtd19
wget -O /tmp/fw.bin http://192.168.31.100:8000/sysupgrade_p4.bin
sysupgrade -n -F /tmp/fw.bin
```

> **⚠️ 必须先擦空两个分区。** `sysupgrade` 第一步是 `ubiattach`，
> 分区里有旧数据（ECC 不兼容）会直接报错中止，根本走不到格式化。
> 擦空后日志出现 `empty MTD device detected` 才会继续。

### 8.5 验证安装

```sh
mount | head -1
# /dev/root on /rom type squashfs      ← 不是 tmpfs

df -h | grep overlay
# /dev/ubi0_1  60.4M  →  /overlay

fw_printenv flag_boot_rootfs
# flag_boot_rootfs=0

ubus call system board
# "rootfs_type": "squashfs"
```

### 8.6 装 LuCI（**不需要 WAN**）

路由器没接 WAN 也能装 —— 用电脑做反向代理：

```bash
# 电脑上（需要有外网）
python tools/_apkproxy.py 8000
```

```sh
# 路由器上（PC_IP = 电脑以太网 IP）
sed -i 's|https://downloads.openwrt.org|http://<PC_IP>:8000|g' \
    /etc/apk/repositories.d/distfeeds.list
apk update          # OK: 11310 distinct packages available
apk add luci
apk add uhttpd-mod-ucode      # ← 必须！见 8.7
```

> ⚠️ **端口冲突**：如果电脑上同时跑着 `python -m http.server 8000`，
> 会和代理抢端口，导致 `wget: exited with error 8`。只留一个。

### 8.7 LuCI 403 的两个坑

装完 LuCI 后访问 `/cgi-bin/luci/` 会返回 **403**，有两个原因：

**坑一：`/etc/config/uhttpd` 里还是旧的 Lua 路径**

```sh
uci show uhttpd.main | grep prefix
# uhttpd.main.lua_prefix='/cgi-bin/luci=/usr/lib/lua/luci/sgi/uhttpd.lua'   ← 文件不存在
```

修复：

```sh
uci del uhttpd.main.lua_prefix
uci add_list uhttpd.main.ucode_prefix='/cgi-bin/luci=/usr/share/ucode/luci/uhttpd.uc'
uci commit uhttpd
```

**坑二：`uhttpd-mod-ucode` 不会自动装**

它不是 `luci` 的依赖。没装时：

- `/usr/lib/uhttpd_ucode.so` 不存在
- `ps | grep uhttpd` 看不到 `-o /cgi-bin/luci -O ...` 参数

```sh
apk add uhttpd-mod-ucode
/etc/init.d/uhttpd restart
ps w | grep '[u]httpd'
# 应该看到：-o /cgi-bin/luci -O /usr/share/ucode/luci/uhttpd.uc
```

**验证成功：**

```bash
curl -s -o /tmp/t.html -w "%{http_code} %{size_download}\n" http://192.168.1.1/cgi-bin/luci/
# → 403 2797          ← 403 是正常的！LuCI 对未登录请求返回 403 + 登录页

grep -o 'luci_username' /tmp/t.html     # 有登录表单就是成功
```

### 8.8 收尾

```sh
passwd root                      # 设密码（空密码会被 dropbear 拒绝）
uci set wireless.radio0.disabled=0
uci set wireless.radio1.disabled=0
uci set wireless.default_radio0.disabled=0
uci set wireless.default_radio1.disabled=0
uci commit wireless && wifi reload
```

---

## 9. 救砖兜底：官方恢复模式

任何一步失败都能用这个回到原厂：

1. 电脑以太网设静态 `192.168.31.100/24`，**不设网关**
2. `python tools/_recovery.py <官方固件.bin>`（DHCP:67 + TFTP:69，自动回 option 66/67）
3. 路由器：按住 Reset → 插电 → 按 20 秒 → 松开
4. 它会自己 `ping` → `dhcp` → `tftp` → `xq_flash_erase` → `Upgrade success!`

> `Trying to ping server.....` 会看起来卡住很久，**其实后面会悄悄走通，别急着 Ctrl-C**。
> 中途打断会导致 `dhcp failed, retry` 反复重试。

刷完可能卡住（串口无声、网口有 link 但不发包），**再断一次电**即可正常启动。

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

我一开始就是这么算的，漏掉了 `crash_syslog`（`0xA00000`，`0x80000`），
导致 `rootfs` 偏移算成 `0xAA0000` 而不是 `0xA80000` —— **正好错 512KB**。
写进去的数据完全错位，刷完还是砖，而且看起来像"固件有问题"。

**一定要用 `smeminfo` 读真实偏移。**

### 10.3 OpenWrt 的分区重映射

| OpenWrt 分区名 | 偏移 | 大小 |
|---|---|---|
| `ubi_kernel` | `0xA80000` | 36 MiB |
| `rootfs` | `0x2E80000` | 81.5 MiB（到 NAND 末尾） |

内核 cmdline：`ubi.mtd=rootfs root=/dev/ubiblock0_0`
→ 内核在 mtd18，rootfs 在 mtd19，`flag_boot_rootfs=0`

---

## 11. 踩坑清单（速查）

| # | 坑 | 现象 | 解决 |
|---|---|---|---|
| 1 | **分区偏移算错** | 刷完还是砖，看起来像固件问题 | 用 `smeminfo` 而不是累加 `/proc/mtd` |
| 2 | **ECC 8-bit vs 芯片 OOB 64** | `ubi_io_read: error -74 (ECC error)` | 改 DTB 的 `nand-ecc-strength` 为 4 |
| 3 | **sysupgrade 假成功** | 报 `successful` 但起不来 | 写和读用的是不同 ECC 的程序 |
| 4 | **分区里有旧数据** | `ubi_attach_mtd_dev: failed to attach, error -22` | 先 `mtd erase` 两个分区 |
| 5 | **`flag_boot_rootfs` 被覆盖** | 设了 1 但启动还是 `rootfs 0` | 把 initramfs 写到 mtd18（槽 0）绕开 |
| 6 | **Reset 按 12 秒不够** | 只有 `detect button press`，没有 `pressed 5 secs` | 按 **20 秒** |
| 7 | **sysupgrade 元数据丢失** | `Image metadata not present` | 别重打包 tar；或加 `-F` |
| 8 | **恢复模式看起来卡住** | `Trying to ping server.....` 不动 | 别 Ctrl-C，它在重试，会走通 |
| 9 | **静态 IP 设了网关** | 电脑断网（默认路由被抢） | 静态 IP **不设网关** |
| 10 | **重打包 sysupgrade** | 元数据 `FWx0` 丢失 | 用 tarfile 等长覆写内核 |
| 11 | **LuCI 403：lua_prefix** | `/cgi-bin/luci/` 返回 403 | 改成 `ucode_prefix` |
| 12 | **LuCI 403：缺 uhttpd-mod-ucode** | uhttpd 启动参数没有 `-o/-O` | `apk add uhttpd-mod-ucode` |
| 13 | **端口 8000 冲突** | `wget: exited with error 8` | HTTP 服务器和代理不能同时占 8000 |
| 14 | **固件与软件包版本不匹配** | LuCI 装上了但 ucode 处理器崩溃/挂住 | 刷**当前** snapshot，让固件和包同版本 |
| 15 | **SSH 空密码被拒** | `User 'root' has blank password, rejected` | 先 `passwd root` 设密码 |
| 16 | **断电时间太短** | 串口无输出、网口有 link 但不发包 | 断电等 **10 秒** |

---

## 12. 工具清单

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

## 13. 常见问题

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

**Q: 以后刷新固件（ImmortalWrt 等）还要打补丁吗？**

**要。** 每个镜像的 DTB 里都是 `nand-ecc-strength = 8`，
不打补丁刷进去就会变砖。流程：下载 → `_ubipatch.py` / `_fitpatch.py` → LuCI 上传刷写。

**Q: 长按 Reset 能进 OpenWrt 的 initramfs 吗？**

不能。长按 Reset 进的是**小米官方恢复**（`xq_upgrade`），它只认小米格式的 `.bin`，
而且会校验文件头。OpenWrt 的 initramfs 是手动 `nand write` 进去的临时安装器。

刷 OpenWrt 固件请用 **LuCI → 系统 → 备份/刷写固件**。

**Q: 系统搞坏了怎么办？**

- 配置坏了：LuCI 里"恢复出厂设置"，或 SSH 删 overlay 文件
- 完全起不来：走第 9 节的恢复模式，或第 8 节的 U-Boot + TFTP 流程
- squashfs 根文件系统是只读的，永远不会被改坏，所有改动都在 overlay 里

**Q: 为什么不直接改 U-Boot 的 ECC？**

U-Boot 的 ECC 是跟着芯片自动选的（OOB 64 → 4-bit），已经是对的。
错的是 OpenWrt 那侧写死的 8-bit。

**Q: 为什么不用 ImageBuilder 重新打包？**

ImageBuilder 不能改 DTS/DTB，只能选包。要改 ECC 必须动设备树 ——
而本文的方案连编译都不需要。

---

## 14. 免责声明

刷机有风险。本文流程已在 **RA74 / ESMT F50D1G41LB / OOB 64** 上完整验证通过，
但不同批次硬件可能仍有差异。

**操作前务必备份全部分区**（`dd if=/dev/mtdN of=...`），并确认手上有可用的官方固件用于恢复。
