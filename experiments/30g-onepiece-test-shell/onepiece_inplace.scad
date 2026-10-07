// EVT-A 30 g 一体模型：实验记录
// 状态：仅 experiment/30g-onepiece-test-shell 使用，不作为正式制造基线。
//
// 该文件记录本次“一体连接”的几何操作。
// 生成时的骨架基准为 30g 全装骨架 v3；扳机/右键帽/摇杆帽来自 EVT-A。
// 三个小圆柱是打印后剪断的临时连接柱。

$fn=36;

// 为便于在实验工作目录中复现，先把 30g 全装骨架 v3 STL 放在本文件同目录。
// EVT-A 三个零件可从仓库 deliverables/evt-a/打印文件/ 复制到本目录。
module cyl_y(x,z,r,y0,y1){
  translate([x,y0,z])
    rotate([-90,0,0])
      cylinder(h=y1-y0, r=r, center=false);
}

union(){
  import("飞鼠_EVT-A_30g全装骨架_v3.stl");
  import("扳机-EVT-A.stl");
  import("右键帽-EVT-A.stl");
  import("摇杆帽.stl");

  // 可剪断连接柱；位置按当前 EVT-A / 骨架 v3 的装配坐标确定。
  cyl_y(0.0,    -11.24, 0.85, -2.50, -0.80); // 扳机 → 骨架
  cyl_y(-36.48,   2.07, 0.90, -3.70, -1.10); // 右键帽 → 右键支撑区
  cyl_y(-32.30,  23.83, 0.90, -3.70, -1.10); // 摇杆帽 → 摇杆支撑区
}
