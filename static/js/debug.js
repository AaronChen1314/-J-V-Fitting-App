// 调试辅助函数
function debugData(V, JExp, label) {
    console.log(`=== ${label} ===`);
    console.log(`V range: [${Math.min(...V)}, ${Math.max(...V)}]`);
    console.log(`J range: [${Math.min(...JExp)}, ${Math.max(...JExp)}]`);
    console.log(`First 5 points:`, V.slice(0,5).map((v,i) => `(${v}, ${JExp[i]})`));
}

// 添加调试日志
const originalUpdateChart = updateChart;
updateChart = function(V, JExp, JFit = null) {
    debugData(V, JExp, "Chart Update");
    originalUpdateChart(V, JExp, JFit);
};
