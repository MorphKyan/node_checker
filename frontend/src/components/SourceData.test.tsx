import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SourceData } from "./SourceData";

afterEach(cleanup);

it("preserves native fields, nested objects, arrays and falsy values as safe text", () => {
  const { container } = render(<SourceData value={{ trust_score: 72, ai_verdict: { reasoning: "原始分析" }, flags: [false, true, 0, null, ""], empty: {}, list: [], html: "<img src=x onerror=alert(1)>" }} />);
  for (const text of ["trust_score", "72", "ai_verdict", "reasoning", "原始分析", "false", "true", "null", '""', "{}", "[]", "<img src=x onerror=alert(1)>"]) {
    expect(screen.getByText(text)).toBeInTheDocument();
  }
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getAllByText("0").length).toBeGreaterThan(0);
});
