# SPICE 模型与 ngspice 兼容

## 来源（以厂商官网为准）

| 类别 | 常见来源 | 格式 | 备注 |
| --- | --- | --- | --- |
| 运放、比较器、LDO、DC-DC | TI（PSpice/TINA）、ADI（LTspice）、ST、onsemi | PSpice `.lib`、LTspice `.asy/.sub` | TI 的部分模型加密，ngspice 不能用；ADI 的 LTspice 模型有的用了 LTspice 专有语法 |
| MOSFET、二极管、BJT | onsemi、Nexperia、Vishay、Diodes Inc. | SPICE `.model`/`.subckt` | 通用性最好 |
| 无源器件（含 MLCC 降额） | Murata SimSurfing、TDK SEAT、Samsung | S 参数、SPICE 等效电路 | 直流偏压特性要看曲线或工具，不是每个模型都包含 |
| 通用模型 | ngspice 自带器件、KiCad Simulation_SPICE 库 | — | 行为模型（B 源、开关）可以搭简化的稳压器 |

下载后放在 `sim/models/`，并在 `sim/models/SOURCES.md` 写清：

- 链接和日期；
- 许可（有的禁止再分发，那就不入库，只留链接和哈希）；
- 版本和适用范围（温度、电压）。

## ngspice 兼容设置

在 deck 里、`.end` 之前加 `.control` 块，或者用 `.options`：

```spice
.options savecurrents      ; 需要测器件电流时
* PSpice 模型：
* .control
*   set ngbehavior=psa
* .endc
```

`sim.py` 用共享库时执行 `run`，不经过 `.control`。需要特殊设置时，可以先装 ngspice 程序（`sudo apt install ngspice`，由用户安装），再用 `--engine cli`；也可以把设置写进 `.spiceinit`。用到的设置要在 deck 注释里说明。

## 拟合简单模型

- **LED**：`D(IS=… N=1.8 RS=2)`。用数据手册的两个点拟合，比如 VF 在 20 mA 时的上下限，算出 IS 的两个角点。示例：`examples/usb-ldo/sim/led_current.cir`。
- **LDO 输入端**：看作恒流或电阻负载（I_in ≈ I_out + Iq）。
- **线缆**：串联 R 加 L。USB 线约 0.5–1.5 µH/m，往返电阻约 0.1–0.3 Ω。
- **MLCC**：C 串 ESR（几 mΩ）和 ESL（约 0.5–1 nH）。容值取工作电压下的有效值，按角点给出。

拟合模型只回答它被拟合的那个问题，并在 deck 注释里写明这一点。
