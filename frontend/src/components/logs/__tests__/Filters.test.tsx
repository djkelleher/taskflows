import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DateRangePicker } from "../DateRangePicker";
import { LogLevelFilter } from "../LogLevelFilter";

describe("log filters", () => {
  it("selects a preset range from the shared popover", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <DateRangePicker
        onChange={onChange}
        value={{ from: "now-1h", to: "now", label: "Last 1 hour" }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Last 1 hour" }));
    await user.click(screen.getByRole("button", { name: "Last 15 minutes" }));

    expect(onChange).toHaveBeenCalledWith({
      from: "now-15m",
      to: "now",
      label: "Last 15 minutes",
    });
    expect(screen.queryByText("Quick ranges")).not.toBeInTheDocument();
  });

  it("prevents an invalid custom range", async () => {
    const user = userEvent.setup();

    render(
      <DateRangePicker
        onChange={vi.fn()}
        value={{ from: "now-1h", to: "now", label: "Last 1 hour" }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Last 1 hour" }));
    await user.click(screen.getByRole("button", { name: "Custom range..." }));
    await user.clear(screen.getByLabelText("End time"));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The end of the range must be after the start.",
    );
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("selects a log level from the shared dropdown", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<LogLevelFilter onChange={onChange} value=".*" />);

    await user.click(screen.getByRole("button", { name: "All Levels" }));
    await user.click(screen.getByRole("menuitem", { name: "Error" }));

    expect(onChange).toHaveBeenCalledWith("error");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
