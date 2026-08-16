import type { WorkItemNode } from "@/lib/types";

export function flattenIds(nodes: WorkItemNode[]): number[] {
  return nodes.flatMap((node) => [node.azure_work_item_id, ...flattenIds(node.children)]);
}

export function collectSelectedIds(nodes: WorkItemNode[]): number[] {
  return nodes.flatMap((node) => [
    ...(node.is_selected ? [node.azure_work_item_id] : []),
    ...collectSelectedIds(node.children),
  ]);
}

export function setSelectedEverywhere(nodes: WorkItemNode[], selected: boolean): WorkItemNode[] {
  return nodes.map((node) => ({ ...node, is_selected: selected, children: setSelectedEverywhere(node.children, selected) }));
}

export const EPIC_FEATURE_STORY_TYPES = new Set(["epic", "feature", "user story", "story"]);

export function setSelectedByType(nodes: WorkItemNode[], allowedTypes: Set<string>): WorkItemNode[] {
  return nodes.map((node) => ({
    ...node,
    is_selected: allowedTypes.has(node.work_item_type.toLowerCase()),
    children: setSelectedByType(node.children, allowedTypes),
  }));
}

export function toggleNode(nodes: WorkItemNode[], azureId: number, selected: boolean): WorkItemNode[] {
  return nodes.map((node) => {
    if (node.azure_work_item_id === azureId) {
      return { ...node, is_selected: selected, children: setSelectedEverywhere(node.children, selected) };
    }
    return { ...node, children: toggleNode(node.children, azureId, selected) };
  });
}
