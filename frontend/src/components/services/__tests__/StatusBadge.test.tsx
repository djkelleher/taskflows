import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../StatusBadge";

describe("StatusBadge", () => {
  it("should render 'Running' for running status", () => {
    render(<StatusBadge status="running" />);

    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("should render 'Running' for active status", () => {
    render(<StatusBadge status="active" />);

    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("should render 'Stopped' for stopped status", () => {
    render(<StatusBadge status="stopped" />);

    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("should render 'Stopped' for inactive status", () => {
    render(<StatusBadge status="inactive" />);

    expect(screen.getByText("Stopped")).toBeInTheDocument();
  });

  it("should render 'Failed' for failed status", () => {
    render(<StatusBadge status="failed" />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("should render status text for unknown status", () => {
    render(<StatusBadge status={"pending" as never} />);

    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("should render 'Unknown' for null/undefined status", () => {
    render(<StatusBadge status={null as never} />);

    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
});
