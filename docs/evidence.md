# 原始证据：启动日志与 ECC 分析

本文记录问题定位过程中的关键日志片段，供复核。

---

## 1. 故障循环（修复前）

```
### main_loop: bootcmd="bootmiwifi"
Hit any key to stop autoboot:  0
detect button press, continue check 5 secs
detect button pressed 5 secs !
confirm to launch xq_upgrade !
cmd=dhcp
...
======== dhcp failed, retry !========
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

U-Boot 每次启动都去挂 `rootfs_1`（mtd19），UBI 头无效 → 写标志位 → 复位，约 9~11 秒一轮。

---

## 2. NAND 芯片识别（U-Boot 侧）

```
NAND:  QPIC controller support serial NAND
ID = 7f7f11c8
Vendor = c8
Device = 11
Serial Nand Device Found With ID : 0xc8 0x11
Serial NAND device Manufature:F50D1G41LB(2M)
Device Size:128 MiB, Page size:2048, Spare Size:64, ECC:4-bit
ESMT F50D1G41LB(2M), disable serial training.
```

关键：**Spare Size 64、ECC 4-bit**。

### 对照：能跑 OpenWrt 的同型号机器

```
spi-nand spi0.0: GigaDevice SPI NAND was found.
spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 128
```

**OOB size 128** —— 这就是差异所在。

---

## 3. 内核侧（OpenWrt 6.18.60）

```
spi-nand spi0.0: ESMT SPI NAND was found.
spi-nand spi0.0: 128 MiB, block size: 128 KiB, page size: 2048, OOB size: 64
[    2.841797] ubi0 warning: ubi_io_read: error -74 (ECC error) while reading 64 bytes from PEB 0:0
[    2.878146] ubi0 warning: ubi_io_read: error -74 (ECC error) while reading 64 bytes from PEB 0:2048
```

芯片识别正确（OOB 64），但 ECC 强度来自设备树（8-bit），于是读写全错。

---

## 4. 设备树里的 ECC 配置

从 `squashfs-sysupgrade.bin` 的 `kernel`（FIT）中解析出的内嵌 DTB：

```
/soc@0/spi@79b0000                      compatible = 'qcom,ipq5018-snand'
/soc@0/spi@79b0000/nand@0               compatible = 'spi-nand'
/soc@0/spi@79b0000/nand@0               nand-ecc-engine    = 47
/soc@0/spi@79b0000/nand@0               nand-ecc-step-size = 512
/soc@0/spi@79b0000/nand@0               nand-ecc-strength  = 8     ← 8-bit
/soc@0/spi@79b0000/nand@0/partitions/partition@a80000  reg = (11010048, 37748736)
/soc@0/spi@79b0000/nand@0/partitions/partition@2e80000 reg = (48758784, 85458944)
/chosen                                 bootargs-append = ' ubi.mtd=rootfs root=/dev/ubiblock0_0 coherent_pool=2M'
```

FIT 结构：

```
/images/kernel-1   type=kernel    data=6076613
/images/kernel-1/hash-1  algo=crc32  value=4B
/images/kernel-1/hash-2  algo=sha1   value=20B
/images/fdt-1      type=flat_dt   data=25441
/images/fdt-1/hash-1     algo=crc32  value=4B
/images/fdt-1/hash-2     algo=sha1   value=20B
```

→ 改 DTB 后必须同步重算 `fdt-1` 的两个哈希。

---

## 5. 补丁前后对比

| 指标 | 补丁前 | 补丁后 |
|---|---|---|
| initramfs 启动时的 ECC 报错行数 | **906 行** | **0 行** |
| `nand-ecc-strength` | 8 | 4 |
| fdt crc32 | `0x18e7b6f0`（旧） | `0xc0eb1050` |
| fdt sha1 | （旧） | `8eef57820bf27220c4e1bddfcf84a4f974a96094` |

---

## 6. sysupgrade 失败的两种典型错误

### 6.1 分区里有旧数据（未擦空）

```
upgrade: Performing system upgrade...
verifying sysupgrade tar file integrity
ubi0: attaching mtd18
ubi0 warning: ubi_io_read: error -74 (ECC error) while reading 64 bytes from PEB 0:0
ubi_attach_mtd_dev: failed to attach mtd18, error -22
```

→ 擦空后变成 `ubi0: empty MTD device detected`，才能继续。

### 6.2 元数据丢失（重打包 tar 导致）

```
upgrade: Image metadata not present
upgrade: Use sysupgrade -F to override this check when downgrading or flashing to vendor firmware
Image check failed.
```

→ 用 `sysupgrade -n -F`，或改为原地覆写内核保持元数据完整。

---

## 7. 安装成功后的状态

```
$ mount | head -3
/dev/root on /rom type squashfs (ro,relatime,errors=continue)

$ df -h
/dev/root    8.5M  8.5M  0  100%  /rom
/dev/ubi0_1  60.4M 72.0K 57.2M  0%  /overlay
overlayfs:/overlay  60.4M 72.0K 57.2M 0% /

$ ubus call system board
{
  "kernel": "6.18.60",
  "model": "Xiaomi Redmi AX5400",
  "board_name": "xiaomi,redmi-ax5400",
  "rootfs_type": "squashfs",
  "release": { "distribution": "OpenWrt", "version": "SNAPSHOT", "revision": "r38203-3d5a743f1f" }
}

$ fw_printenv flag_boot_rootfs
flag_boot_rootfs=0

$ iwinfo
phy0-ap0  ESSID: "OpenWrt"  Channel: 1  (2.412 GHz)  HE20
phy1-ap0  ESSID: "OpenWrt"  Channel: 36 (5.180 GHz)  HE80
```

---

## 8. flag_boot_rootfs 被覆盖的证据

手动设置并保存：

```
IPQ5018# setenv flag_boot_rootfs 1
IPQ5018# saveenv
Saving Environment to NAND...
Erasing NAND...
Writing to NAND... OK
IPQ5018# printenv flag_boot_rootfs
flag_boot_rootfs=1          ← 回读确认是 1
```

重启后：

```
boot from rootfs 0          ← 又变回 0 了！
miwifi: check crash in rmem !
ubi0: attaching mtd1
...
Erasing NAND...             ← bootmiwifi 在启动时重写了 env
Writing to NAND... OK
```

**结论：`bootmiwifi` 每次启动都会重写 env 并翻转标志位，手动修改无效。**

**解法：把 initramfs 直接写到 mtd18（槽 0）**，这样不管标志是几都会启动它。

```
nand erase 0xA80000 0x2400000
nand write 0x44000000 0xA80000 0xF80000
reset
```

之后启动日志：

```
boot from rootfs 0
...
Please press Enter to activate this console     ← initramfs 成功启动
procd ×5   br-lan ×8
ECC 报错 0 行
```

---

## 9. LuCI 403 的诊断过程

### 9.1 现象

```
$ wget -O /dev/null http://127.0.0.1/cgi-bin/luci/
Connecting to 127.0.0.1:80
HTTP error 403
```

日志里没有任何 uhttpd 报错。

### 9.2 第一次定位：uhttpd 启动参数缺失

```
$ ps w | grep '[u]httpd'
/usr/sbin/uhttpd -f -h /www -r OpenWrt -x /cgi-bin -u /ubus -t 60 -T 30 ...
                                          ↑ 没有 -o / -O
```

对比正常情况应该有：

```
/usr/sbin/uhttpd ... -x /cgi-bin -u /ubus -o /cgi-bin/luci -O /usr/share/ucode/luci/uhttpd.uc
```

原因：`uhttpd-mod-ucode` 未安装。

```
$ ls /usr/lib/uhttpd_*.so
/usr/lib/uhttpd_ubus.so          ← 只有 ubus 模块
```

### 9.3 配置问题

```
$ uci show uhttpd.main | grep prefix
uhttpd.main.cgi_prefix='/cgi-bin'
uhttpd.main.lua_prefix='/cgi-bin/luci=/usr/lib/lua/luci/sgi/uhttpd.lua'   ← 旧路径
uhttpd.main.ubus_prefix='/ubus'
```

而实际文件是：

```
$ ls /usr/share/ucode/luci/uhttpd.uc
-rw-r--r--  root  root  204  /usr/share/ucode/luci/uhttpd.uc
```

### 9.4 修复后

```
$ apk add uhttpd-mod-ucode
$ uci del uhttpd.main.lua_prefix
$ uci add_list uhttpd.main.ucode_prefix='/cgi-bin/luci=/usr/share/ucode/luci/uhttpd.uc'
$ uci commit uhttpd && /etc/init.d/uhttpd restart

$ ps w | grep '[u]httpd'
/usr/sbin/uhttpd ... -o /cgi-bin/luci -O /usr/share/ucode/luci/uhttpd.uc    ← 正确
```

### 9.5 验证

```bash
$ curl -s -o /tmp/t.html -w "%{http_code} %{size_download}\n" \
    http://192.168.1.1/cgi-bin/luci/
403 2797                    ← 403 是正常的，LuCI 对未登录请求返回 403 + 登录页

$ head -5 /tmp/t.html
<!DOCTYPE html>
<html lang="en" >
	<head>
		<meta charset="utf-8">
		<title>OpenWrt | Overview</title>

$ grep -o 'luci_username' /tmp/t.html
luci_username               ← 登录表单存在，LuCI 正常工作
```

---

## 10. 固件与软件包版本错配的证据

### 10.1 第一次尝试（r38203 + 今天 snapshot 的包）

```
$ apk add luci
(26/26) Installing luci (26.315.63089~042f322)
OK: 26.7 MiB in 172 packages          ← 安装"成功"
```

但访问网页：

```
HTTP error 403
```

前台跑 uhttpd 测试：

```
$ uhttpd -f -h /www -x /cgi-bin -o /cgi-bin/luci \
         -O /usr/share/ucode/luci/uhttpd.uc -p 8080 &
$ wget -O - http://127.0.0.1:8080/cgi-bin/luci/
(null)                   0   - stalled -
Connection reset prematurely          ← ucode 处理器崩溃
```

**原因**：固件是 11月11日 的 r38203，而 `apk` 只能装**当前** snapshot 的包
（旧构建的包已从服务器移除）。LuCI 在这两个版本之间从 Lua 迁到了 ucode，
新旧组件混装导致 ucode 处理器崩溃。

### 10.2 解决方案：刷当前 snapshot

```
OpenWrt SNAPSHOT r38209-ada52cc7ed     ← 今天的构建
```

固件和软件包同一版本后，同样的 `apk add luci` + 两处配置修复，LuCI 立刻正常。

### 10.3 反向代理日志（无 WAN 装包）

```
[proxy] 200 /snapshots/packages/aarch64_cortex-a53/base/packages.adb (117233 字节)
...
$ apk update
OK: 11310 distinct packages available
```
