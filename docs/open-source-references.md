# 成熟开源项目参考记录

核对日期：2026-10-16。按参赛人要求，仅筛选超过5,000星、建立多年的相关项目，未以近期小型参赛作品作为参考。星数来自GitHub仓库API当次查询，会随时间变化。

| 项目 | 当次星数 / 建立时间 | 许可 | 与本项目相关的参考方式 |
| --- | --- | --- | --- |
| [OSMnx](https://github.com/gboeing/osmnx) | 5,876 / 2016年 | MIT | 以明确起点、路网耗时和可达范围解释步行分析；[官方等时圈示例](https://github.com/gboeing/osmnx-examples/blob/main/notebooks/13-isolines-isochrones.ipynb)作为方法表达参考。 |
| [GraphHopper](https://github.com/graphhopper/graphhopper) | 6,731 / 2012年 | Apache-2.0 | 起点与终点、路线结果和耗时各自明确；沿道路算路与直线距离分开解释。 |
| [kepler.gl](https://github.com/keplergl/kepler.gl) | 12,046 / 2018年 | MIT | [官方用户指南](https://github.com/keplergl/kepler.gl/blob/master/docs/user-guides/README.md)中的分层、过滤、图例和地图解释方式，转化为本项目的现状/方案切换与明确图例。 |

本轮参考的是方法和交互表达，由本项目在现有原生HTML/CSS、Leaflet和百度网页地图上实现；没有将上述项目加入运行依赖，也没有导入它们的代码、地图数据或图片。真实测时、POI与坐标仍来自本项目已接入的百度链路。

具体改动：真实体检为已配置环境的默认入口；离线示例聚焦单类养老服务；现状和方案一/二分别显示，地图仅将程序实际算出的新增覆盖位置变色；新增设施类型由用户需求约束，不能用其他最弱类别替代。工具、页面和报告继续标明采样、未知、来源与现实核验限制。
