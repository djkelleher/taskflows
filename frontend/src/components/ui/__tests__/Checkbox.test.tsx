import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Checkbox } from "../Checkbox";

describe("Checkbox", () => {
  it("should render without label", () => {
    render(<Checkbox />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeInTheDocument();
  });

  it("should render with label", () => {
    render(<Checkbox label="Accept terms" />);

    const checkbox = screen.getByRole("checkbox");
    const label = screen.getByText("Accept terms");

    expect(checkbox).toBeInTheDocument();
    expect(label).toBeInTheDocument();
  });

  it("should generate ID from label", () => {
    render(<Checkbox label="Accept Terms" />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toHaveAttribute("id", "accept-terms");
  });

  it("should use custom ID when provided", () => {
    render(<Checkbox label="Test" id="custom-id" />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toHaveAttribute("id", "custom-id");
  });

  it("should handle checked state", () => {
    render(<Checkbox checked={true} readOnly />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeChecked();
  });

  it("should handle unchecked state", () => {
    render(<Checkbox checked={false} readOnly />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
  });

  it("should call onChange when clicked", async () => {
    let checked = false;
    const handleChange = () => {
      checked = true;
    };

    render(<Checkbox onChange={handleChange} />);

    const checkbox = screen.getByRole("checkbox");
    await userEvent.click(checkbox);

    expect(checked).toBe(true);
  });

  it("should apply custom className", () => {
    render(<Checkbox className="custom-class" />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toHaveClass("custom-class");
  });

  it("should support disabled state", () => {
    render(<Checkbox disabled />);

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeDisabled();
  });
});
