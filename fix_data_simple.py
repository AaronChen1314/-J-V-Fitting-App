import pandas as pd
import numpy as np

# 读取数据
file_nbg = r"钙钙\0-1-nbg真实.csv"
file_wbg = r"钙钙\0-1-wbg-真实.csv"

df_nbg = pd.read_csv(file_nbg)
df_wbg = pd.read_csv(file_wbg)

# 分析结果
# 0-1-nbg真实.csv: V=0时J为正值，趋势正常 - 不需要修改
# 0-1-wbg-真实.csv: V=0时J为负值，需要取反

# 创建修复后的数据
df_nbg_fixed = df_nbg.copy()

df_wbg_fixed = df_wbg.copy()
df_wbg_fixed.iloc[:,1] = -df_wbg_fixed.iloc[:,1]

# 保存修复后的数据
df_nbg_fixed.to_csv(r"钙钙\0-1-nbg真实_fixed.csv", index=False)
df_wbg_fixed.to_csv(r"钙钙\0-1-wbg-真实_fixed.csv", index=False)

print("Fixed data saved:")
print("  - 钙钙\\0-1-nbg真实_fixed.csv")
print("  - 钙钙\\0-1-wbg-真实_fixed.csv")
print("\nFix summary:")
print("  - 0-1-nbg真实.csv: No change needed (normal curve)")
print("  - 0-1-wbg-真实.csv: Inverted current sign to match PV curve standard")
