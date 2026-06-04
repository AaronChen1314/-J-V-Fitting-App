import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 读取两份数据
file_nbg = r"钙钙\0-1-nbg真实.csv"
file_wbg = r"钙钙\0-1-wbg-真实.csv"

df_nbg = pd.read_csv(file_nbg)
df_wbg = pd.read_csv(file_wbg)

print("=== 数据核验报告 ===")
print("\n【0-1-nbg真实.csv】")
print(f"列名: {df_nbg.columns.tolist()}")
print(f"数据形状: {df_nbg.shape}")
print(f"电压范围: {df_nbg.iloc[:,0].min():.3f} ~ {df_nbg.iloc[:,0].max():.3f} V")
print(f"电流范围: {df_nbg.iloc[:,1].min():.3f} ~ {df_nbg.iloc[:,1].max():.3f} mA/cm²")
print(f"平均电流: {df_nbg.iloc[:,1].mean():.3f} mA/cm²")

print("\n【0-1-wbg-真实.csv】")
print(f"列名: {df_wbg.columns.tolist()}")
print(f"数据形状: {df_wbg.shape}")
print(f"电压范围: {df_wbg.iloc[:,0].min():.3f} ~ {df_wbg.iloc[:,0].max():.3f} V")
print(f"电流范围: {df_wbg.iloc[:,1].min():.3f} ~ {df_wbg.iloc[:,1].max():.3f} mA/cm²")
print(f"平均电流: {df_wbg.iloc[:,1].mean():.3f} mA/cm²")

# 分析数据特征
print("\n=== 光伏J-V曲线特征分析 ===")
print("标准光伏J-V曲线特征：")
print("1. 短路点 (V≈0): J为正值 (Jsc)")
print("2. 开路点 (J≈0): V为正值 (Voc)")
print("3. 随着V增加，J从正值下降到0，再变为负值")

# 检查两份数据的电流方向
print("\n【0-1-nbg真实.csv】：")
v_near_zero_nbg = df_nbg.iloc[(df_nbg.iloc[:,0]-0).abs().idxmin()]
print(f"V≈0 点: V={v_near_zero_nbg.iloc[0]:.6f}, J={v_near_zero_nbg.iloc[1]:.3f}")
if v_near_zero_nbg.iloc[1] > 0:
    print("✓ 符合光伏曲线特征：V=0时J为正值")
else:
    print("✗ 需要修正：V=0时J应为正值")

print("\n【0-1-wbg-真实.csv】：")
v_near_zero_wbg = df_wbg.iloc[(df_wbg.iloc[:,0]-0).abs().idxmin()]
print(f"V≈0 点: V={v_near_zero_wbg.iloc[0]:.6f}, J={v_near_zero_wbg.iloc[1]:.3f}")
if v_near_zero_wbg.iloc[1] < 0:
    print("✗ 需要修正：V=0时J为负值，应该取反")
else:
    print("✓ 符合光伏曲线特征：V=0时J为正值")

# 创建修复后的数据
print("\n=== 数据修复方案 ===")

# 修复方案1：nbg数据 - 检查是否需要调整
df_nbg_fixed = df_nbg.copy()
# 检查nbg数据的趋势
j_at_low_v_nbg = df_nbg[df_nbg.iloc[:,0] < 0.2].iloc[:,1].mean()
j_at_high_v_nbg = df_nbg[df_nbg.iloc[:,0] > 0.6].iloc[:,1].mean()

if j_at_low_v_nbg > j_at_high_v_nbg:
    print("✓ 0-1-nbg真实.csv 趋势正常：J随V增加而下降")
else:
    print("✗ 0-1-nbg真实.csv 需要检查趋势")

# 修复方案2：wbg数据 - 电流取反
df_wbg_fixed = df_wbg.copy()
df_wbg_fixed.iloc[:,1] = -df_wbg_fixed.iloc[:,1]
print("✓ 0-1-wbg-真实.csv 已修复：将电流取反")

# 保存修复后的数据
df_nbg_fixed.to_csv(r"钙钙\0-1-nbg真实_fixed.csv", index=False)
df_wbg_fixed.to_csv(r"钙钙\0-1-wbg-真实_fixed.csv", index=False)
print(f"\n修复后的数据已保存：")
print(f"  - 钙钙\\0-1-nbg真实_fixed.csv")
print(f"  - 钙钙\\0-1-wbg-真实_fixed.csv")

# 可视化对比
plt.figure(figsize=(14, 6))

plt.subplot(1, 2, 1)
plt.plot(df_nbg.iloc[:,0], df_nbg.iloc[:,1], 'bo-', label='原始', alpha=0.7)
plt.plot(df_nbg_fixed.iloc[:,0], df_nbg_fixed.iloc[:,1], 'r-', label='修复后', linewidth=2, alpha=0.5)
plt.xlabel('Voltage (V)')
plt.ylabel('Current Density (mA/cm²)')
plt.title('0-1-nbg真实.csv')
plt.legend()
plt.grid(True, alpha=0.3)

plt.subplot(1, 2, 2)
plt.plot(df_wbg.iloc[:,0], df_wbg.iloc[:,1], 'bo-', label='原始', alpha=0.7)
plt.plot(df_wbg_fixed.iloc[:,0], df_wbg_fixed.iloc[:,1], 'r-', label='修复后', linewidth=2, alpha=0.5)
plt.xlabel('Voltage (V)')
plt.ylabel('Current Density (mA/cm²)')
plt.title('0-1-wbg-真实.csv')
plt.legend()
plt.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(r"钙钙\data_fix_comparison.png", dpi=150)
print("\n对比图已保存：钙钙\\data_fix_comparison.png")

print("\n=== 修复完成 ===")
