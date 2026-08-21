import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Breadcrumb } from "./Breadcrumb";

describe("Breadcrumb", () => {
  it("renders linked items as links and the final item as the current page", () => {
    render(
      <Breadcrumb
        items={[{ label: "Home", href: "/" }, { label: "Executions", href: "/executions" }, { label: "demo-project" }]}
      />
    );

    const home = screen.getByRole("link", { name: "Home" });
    expect(home).toHaveAttribute("href", "/");

    const executions = screen.getByRole("link", { name: "Executions" });
    expect(executions).toHaveAttribute("href", "/executions");

    const current = screen.getByText("demo-project");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(current.tagName).not.toBe("A");
  });

  it("renders a link for the final item when it has an href", () => {
    render(<Breadcrumb items={[{ label: "Home", href: "/" }, { label: "demo-project", href: "/projects/1" }]} />);
    expect(screen.getByRole("link", { name: "demo-project" })).toHaveAttribute("href", "/projects/1");
  });
});
