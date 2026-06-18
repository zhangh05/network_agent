export type AgentStreamState = {
  draft: string;
};

export function beginModelStep(_previous: string = ""): AgentStreamState {
  return { draft: "" };
}

export function discardToolCallDraft(state: AgentStreamState): void {
  state.draft = "";
}

export function finalizeStreamText(streamedText: string, finalResponse: string): string {
  return finalResponse || streamedText;
}
