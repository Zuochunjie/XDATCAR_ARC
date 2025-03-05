# -*- coding: utf-8 -*-
"""
XDATCAR转Materials Studio ARC文件脚本
功能：
1. 将VASP的XDATCAR分子动力学轨迹转换为Materials Studio可读的ARC格式
2. 自动处理可变晶胞轨迹
3. 保留元素类型信息
4. 正确处理分数坐标到笛卡尔坐标的转换

修改点：
1. 每帧输出两个 "end"
2. 只有最后一帧的 "end" 后面加空行，其余帧不加
3. 时间戳使用脚本当前执行时的实际时间
"""

import math
import sys
from datetime import datetime

# ---------------------------- 配置参数 ----------------------------
input_file = sys.argv[1] if len(sys.argv) > 1 else 'XDATCAR'  # 输入文件名
output_file = sys.argv[2] if len(sys.argv) > 2 else 'XDATCAR.arc'  # 输出文件名


# ----------------------------------------------------------------

def main():
    # 获取脚本执行时的当前时间戳（作为所有帧的默认时间戳）
    # 如果想让不同帧有不同的时间戳，可以把此逻辑放到循环内部
    current_timestamp = datetime.now().strftime('%a %b %d %H:%M:%S %Y')

    # 读取所有非空行
    with open(input_file, 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    if len(lines) < 6:
        raise ValueError('XDATCAR文件格式错误：行数不足')

    # ---------------------- 解析头部信息 ----------------------
    title = lines[0]  # 文件标题行
    scale = float(lines[1].split()[0])  # 晶格缩放因子

    # 解析初始晶格向量(3x3矩阵)
    cell_vectors = [
        [scale * float(x) for x in lines[2].split()],
        [scale * float(x) for x in lines[3].split()],
        [scale * float(x) for x in lines[4].split()]
    ]

    # 判断元素类型行是否存在(第5或第6行)
    if lines[5].split()[0].isalpha():  # 如果第5行包含元素符号
        elements = lines[5].split()
        counts = list(map(int, lines[6].split()))
        header_offset = 7
    else:
        elements = None
        counts = list(map(int, lines[5].split()))
        header_offset = 6

    total_atoms = sum(counts)  # 体系总原子数

    # 生成元素符号列表(处理无元素符号的情况)
    atom_symbols = []
    if elements:
        for sym, cnt in zip(elements, counts):
            atom_symbols.extend([sym] * cnt)
    else:  # 使用A/B/C占位符
        placeholder = [chr(65 + i) for i in range(len(counts))]
        for ph, cnt in zip(placeholder, counts):
            atom_symbols.extend([ph] * cnt)
    atom_symbols = atom_symbols[:total_atoms]  # 确保长度正确

    # ---------------------- 定位所有帧 ----------------------
    frame_starts = [
        i for i, ln in enumerate(lines)
        if ln.lower().startswith('direct configuration')
    ]
    if not frame_starts:
        raise ValueError('未找到分子动力学轨迹帧')

    # ---------------------- 轨迹参数检测 ----------------------
    variable_cell = False  # 是否可变晶胞
    if len(frame_starts) > 1:
        frames_interval = frame_starts[1] - frame_starts[0]
        # 标准固定晶胞每帧间隔应为原子数+1行(坐标行+标题行)
        if frames_interval != total_atoms + 1:
            variable_cell = True

    # ---------------------- 准备输出 ----------------------
    arc = [
        '!BIOSYM archive 3',  # ARC文件头
        'PBC=ON'  # 周期性边界标记
    ]

    current_frame = 0  # 当前帧序号(从0开始)
    total_frames = len(frame_starts)

    # ---------------------- 处理每帧数据 ----------------------
    for idx, frame_idx in enumerate(frame_starts):
        # 读取晶胞信息(如果是可变晶胞)
        if variable_cell:
            # 检查晶胞信息格式：可能有缩放因子行
            next_line = lines[frame_idx + 1]
            try:
                float(next_line)  # 测试能否被转为浮点数
                # 如果能转换为浮点数，说明这一行是缩放因子
                new_scale = float(next_line)
                new_cell = [
                    [new_scale * float(x) for x in lines[frame_idx + 2].split()],
                    [new_scale * float(x) for x in lines[frame_idx + 3].split()],
                    [new_scale * float(x) for x in lines[frame_idx + 4].split()]
                ]
                coord_start = frame_idx + 5
            except ValueError:
                # 无缩放因子
                new_cell = [
                    [float(x) for x in lines[frame_idx + 1].split()],
                    [float(x) for x in lines[frame_idx + 2].split()],
                    [float(x) for x in lines[frame_idx + 3].split()]
                ]
                coord_start = frame_idx + 4
        else:
            new_cell = cell_vectors  # 使用初始晶胞
            coord_start = frame_idx + 1

        # 检查坐标数据有效性
        if coord_start + total_atoms > len(lines):
            print(f'警告：第{current_frame}帧数据不完整，已跳过')
            continue

        # 转换分数坐标为笛卡尔坐标
        cartesian_coords = []
        for i_atom in range(total_atoms):
            frac = list(map(float, lines[coord_start + i_atom].split()[:3]))
            # 应用周期性边界条件
            frac = [x - math.floor(x) for x in frac]
            # 分数坐标转笛卡尔坐标
            x = sum(frac[j] * new_cell[j][0] for j in range(3))
            y = sum(frac[j] * new_cell[j][1] for j in range(3))
            z = sum(frac[j] * new_cell[j][2] for j in range(3))
            cartesian_coords.append((x, y, z))

        # ---------------------- 构建ARC帧头 ----------------------
        # 计算晶胞参数 (a, b, c, α, β, γ)
        a = math.sqrt(sum(x ** 2 for x in new_cell[0]))
        b = math.sqrt(sum(x ** 2 for x in new_cell[1]))
        c = math.sqrt(sum(x ** 2 for x in new_cell[2]))

        def calc_angle(v1, v2):
            """计算两个向量之间的夹角(度数)"""
            dot_val = sum(v1[i] * v2[i] for i in range(3))
            norm_v1 = math.sqrt(sum(_x ** 2 for _x in v1))
            norm_v2 = math.sqrt(sum(_x ** 2 for _x in v2))
            return math.degrees(math.acos(dot_val / (norm_v1 * norm_v2)))

        alpha = calc_angle(new_cell[1], new_cell[2])
        beta = calc_angle(new_cell[0], new_cell[2])
        gamma = calc_angle(new_cell[0], new_cell[1])

        # 写入帧头
        arc.append(f'frame {current_frame}')
        arc.append(f'!DATE {current_timestamp}')  # 使用当前时间戳
        arc.append(f'PBC {a:10.5f}{b:10.5f}{c:10.5f}'
                   f'{alpha:10.5f}{beta:10.5f}{gamma:10.5f}')

        # ---------------------- 写入原子坐标 ----------------------
        element_counter = {}
        for (sym, (x, y, z)) in zip(atom_symbols, cartesian_coords):
            element_counter[sym] = element_counter.get(sym, 0) + 1
            atom_name = f"{sym}{element_counter[sym]}"
            # ARC格式中：原子名 X Y Z XXXX 1 xx 元素 电荷
            arc.append(f"{atom_name:5}{x:15.9f}{y:15.9f}{z:15.9f}"
                       f" XXXX 1      xx      {sym:2}  0.000")

        # ---------------------- 帧结束标记 ----------------------
        arc.append('end')
        arc.append('end')

        # 如果是「最后一帧」，在第二个end后面加一个空行
        # 如果不是最后一帧，则不加空行
        if idx == total_frames - 1:
            arc.append('')

        current_frame += 1

    # ---------------------- 写入文件 ----------------------
    with open(output_file, 'w') as f:
        f.write('\n'.join(arc))
    print(f"转换完成：共转换 {current_frame} 帧 -> {output_file}")


if __name__ == '__main__':
    main()
