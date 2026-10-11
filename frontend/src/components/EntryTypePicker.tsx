import levelIcon from "../assets/monitoring-icons/level.svg";
import tiltIcon from "../assets/monitoring-icons/tilt.svg";
import horizontalIcon from "../assets/monitoring-icons/horizontal.svg";
import axialIcon from "../assets/monitoring-icons/axial.svg";
import waterIcon from "../assets/monitoring-icons/water.svg";
import inclinometerIcon from "../assets/monitoring-icons/inclinometer.svg";

export const entryTypes = [
  {
    key: "level",
    name: "水准",
    description: "高程测量 · 沉降变化",
    icon: levelIcon,
  },
  {
    key: "tilt",
    name: "倾斜",
    description: "关联水准 · 两点倾斜",
    icon: tiltIcon,
  },
  {
    key: "horizontal",
    name: "水平位移",
    description: "X / Y 坐标录入",
    icon: horizontalIcon,
  },
  {
    key: "axial",
    name: "支撑轴力",
    description: "传感器参数 · 频率录入",
    icon: axialIcon,
  },
  {
    key: "water",
    name: "水位",
    description: "管口高程 · 水位读数",
    icon: waterIcon,
  },
  {
    key: "inclinometer",
    name: "深层水平位移",
    description: "孔号参数 · 深度测值",
    icon: inclinometerIcon,
  },
];

export function entryLabel(key: string) {
  const [type, ...parts] = key.split(":");
  const label = entryTypes.find((item) => item.key === type)?.name || type;
  return parts.length ? `${label} · ${parts.join(":")}` : label;
}

export function EntryTypePicker({
  onSelect,
}: {
  onSelect: (type: string) => void;
}) {
  return (
    <section className="panel entry-page entry-type-picker">
      <div className="panel-heading">
        <div>
          <h2>选择单期监测类型</h2>
          <p>选择监测类型，进入对应的参数设置和数据录入表格。</p>
        </div>
      </div>
      <div className="entry-type-grid">
        {entryTypes.map((type) => (
          <button
            key={type.key}
            type="button"
            className="entry-type-card"
            aria-label={type.name}
            onClick={() => onSelect(type.key)}
          >
            <img src={type.icon} alt="" />
            <strong>{type.name}</strong>
            <span>{type.description}</span>
          </button>
        ))}
      </div>
      <p className="entry-picker-note">
        各监测类型独立录入；已保存的数据可在对应类型中继续编辑。
      </p>
    </section>
  );
}
