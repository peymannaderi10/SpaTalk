import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TeamTab } from "./TeamTab";

/**
 * The Team page: who a caller may ask for by name, and which of the tenant's
 * services each person performs. Rows live in `config.team`; the services a
 * person can be ticked for are the tenant's own `config.services`, by id, and
 * an empty list means the person does everything.
 */

/** A trimmed copy of what `GET /internal/schema/tenant-config` serves. */
const schema = {
  $defs: {
    TeamMember: {
      properties: {
        name: { maxLength: 80, title: "Name", type: "string" },
        role: { default: "", title: "Role", type: "string" },
        services: {
          items: { type: "string" },
          title: "Services",
          type: "array",
        },
      },
      required: ["name"],
      title: "TeamMember",
      type: "object",
    },
  },
  properties: {
    team: {
      items: { $ref: "#/$defs/TeamMember" },
      title: "Team",
      type: "array",
    },
  },
  title: "TenantConfig",
  type: "object",
};

const config = {
  services: [
    { id: "hydrafacial", name: "HydraFacial", category: "facials" },
    { id: "laser_hair", name: "Laser hair removal", category: "laser" },
    { id: "consult", name: "Consultation", category: "consultation" },
    { id: "", name: "Not saved yet", category: "facials" },
  ],
  team: [
    { name: "Helen", role: "Aesthetician", services: ["hydrafacial"] },
    { name: "Dr. Rao", role: "Medical director", services: [] },
  ],
};

function mount(overrides: Partial<Parameters<typeof TeamTab>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <TeamTab
      config={config}
      schema={schema}
      onChange={onChange}
      disabled={false}
      {...overrides}
    />,
  );
  return onChange;
}

describe("the Team tab", () => {
  it("renders one row per member, with what they do ticked", () => {
    mount();
    expect(screen.getByTestId("team-0-name")).toHaveValue("Helen");
    expect(screen.getByTestId("team-0-role")).toHaveValue("Aesthetician");
    expect(screen.getByTestId("team-1-name")).toHaveValue("Dr. Rao");
    expect(screen.queryByTestId("team-2")).toBeNull();

    expect(screen.getByTestId("team-0-service-hydrafacial")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByTestId("team-0-service-laser_hair")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByTestId("team-1-service-hydrafacial")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(
      screen.getAllByText(
        "Leave every service unticked for someone who does everything.",
      ),
    ).toHaveLength(2);
  });

  it("groups the services by category, labelled by name, and skips one with no id", () => {
    mount();
    const row = within(screen.getByTestId("team-0"));
    expect(row.getByText("facials")).toBeInTheDocument();
    expect(row.getByText("laser")).toBeInTheDocument();
    expect(row.getByText("consultation")).toBeInTheDocument();
    expect(row.getByText("Laser hair removal")).toBeInTheDocument();
    expect(row.queryByText("Not saved yet")).toBeNull();
    expect(row.getAllByRole("checkbox")).toHaveLength(3);
  });

  it("ticking a service adds its id to that member and nobody else", () => {
    const onChange = mount();
    fireEvent.click(screen.getByTestId("team-0-service-laser_hair"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0];
    expect(next.team[0].services).toEqual(["hydrafacial", "laser_hair"]);
    expect(next.team[1]).toEqual(config.team[1]);
    expect(next.services).toEqual(config.services);
  });

  it("unticking a service removes its id", () => {
    const onChange = mount();
    fireEvent.click(screen.getByTestId("team-0-service-hydrafacial"));
    const next = onChange.mock.calls[0][0];
    expect(next.team[0]).toEqual({
      name: "Helen",
      role: "Aesthetician",
      services: [],
    });
  });

  it("edits a name through onChange, bounded by the schema", () => {
    const onChange = mount();
    expect(screen.getByTestId("team-0-name")).toHaveAttribute(
      "maxlength",
      "80",
    );
    fireEvent.change(screen.getByTestId("team-1-role"), {
      target: { value: "Physician" },
    });
    const next = onChange.mock.calls[0][0];
    expect(next.team[1]).toEqual({
      name: "Dr. Rao",
      role: "Physician",
      services: [],
    });
  });

  it("adds an empty member who does everything", () => {
    const onChange = mount();
    fireEvent.click(screen.getByTestId("add-team-member"));
    const next = onChange.mock.calls[0][0];
    expect(next.team).toHaveLength(3);
    expect(next.team[2]).toEqual({ name: "", role: "", services: [] });
  });

  it("drops a member on Remove", () => {
    const onChange = mount();
    fireEvent.click(screen.getByTestId("remove-team-1"));
    const next = onChange.mock.calls[0][0];
    expect(next.team).toEqual([config.team[0]]);
  });

  it("marks the field a refused save named, and no other", () => {
    mount({ errors: [{ path: ["team", "1", "name"] }] });
    expect(screen.getByTestId("team-1-name")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByTestId("team-0-name")).not.toHaveAttribute(
      "aria-invalid",
    );
    expect(screen.getByTestId("team-1-role")).not.toHaveAttribute(
      "aria-invalid",
    );
  });

  it("offers no add, remove or tick when the page is read only", () => {
    mount({ disabled: true });
    expect(screen.queryByTestId("add-team-member")).toBeNull();
    expect(screen.queryByTestId("remove-team-0")).toBeNull();
    expect(screen.getByTestId("team-0-name")).toBeDisabled();
    expect(screen.getByTestId("team-0-service-hydrafacial")).toBeDisabled();
  });

  it("says so when there is nobody yet, and when there is no service to tick", () => {
    mount({
      config: {
        services: [],
        team: [{ name: "Helen", role: "", services: [] }],
      },
    });
    expect(screen.getByTestId("team-0-no-services")).toBeInTheDocument();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("shows an empty state with nobody on the team", () => {
    mount({ config: { services: config.services, team: [] } });
    expect(screen.getByTestId("team-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("team-0")).toBeNull();
  });
});
