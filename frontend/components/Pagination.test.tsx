import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Pagination } from "./Pagination";

describe("Pagination", () => {
  it("renders nothing when everything fits on one page", () => {
    const { container } = render(<Pagination total={5} limit={20} offset={0} onOffsetChange={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("disables Previous on the first page and Next on the last page", () => {
    render(<Pagination total={40} limit={20} offset={20} onOffsetChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("calls onOffsetChange with the next page's offset", async () => {
    const onOffsetChange = vi.fn();
    render(<Pagination total={60} limit={20} offset={0} onOffsetChange={onOffsetChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onOffsetChange).toHaveBeenCalledWith(20);
  });

  it("calls onOffsetChange with the previous page's offset, clamped at zero", async () => {
    const onOffsetChange = vi.fn();
    render(<Pagination total={60} limit={20} offset={20} onOffsetChange={onOffsetChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onOffsetChange).toHaveBeenCalledWith(0);
  });
});
