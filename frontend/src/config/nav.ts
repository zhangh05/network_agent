import type { ComponentType } from "react";
import {
  IconBox,
  IconChat,
  IconHistory,
  IconLayers,
  IconBolt,
  IconShield,
  IconSettings,
} from "../components/Icon";

export interface NavItem {
  to: string;
  label: string;
  testid: string;
  Icon: ComponentType<{ size?: number }>;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/workbench", label: "工作台", testid: "nav-workbench", Icon: IconChat },
  { to: "/runs", label: "运行与作业", testid: "nav-runs", Icon: IconHistory },
  { to: "/capabilities", label: "能力矩阵", testid: "nav-capabilities", Icon: IconLayers },
  { to: "/knowledge", label: "知识库", testid: "nav-knowledge", Icon: IconBox },
  { to: "/artifacts", label: "制品", testid: "nav-artifacts", Icon: IconBox },
  { to: "/memory", label: "记忆", testid: "nav-memory", Icon: IconBox },
  { to: "/packet", label: "报文分析", testid: "nav-packet", Icon: IconBolt },
  { to: "/cmdb", label: "设备资产", testid: "nav-cmdb", Icon: IconLayers },
  { to: "/assurance", label: "网络保障", testid: "nav-assurance", Icon: IconShield },
  { to: "/diagnostics", label: "系统诊断", testid: "nav-diagnostics", Icon: IconShield },
  { to: "/settings", label: "系统设置", testid: "nav-settings", Icon: IconSettings },
];
