import { expect, test } from "vitest"
import { getSkillMode, setSkillMode } from "./skill-modes"

test("selects an off skill as available", () => {
  const next = setSkillMode({}, "alpha", "available", false)
  expect(next.executor_skills).toEqual(["alpha"])
  expect(next.required_executor_skills).toEqual([])
  expect(getSkillMode(next, "alpha", false)).toBe("available")
})

test("upgrades an available skill to required without duplication", () => {
  const next = setSkillMode(
    { executor_skills: ["alpha"], required_executor_skills: [] },
    "alpha",
    "required",
    false,
  )
  expect(next.executor_skills).toEqual([])
  expect(next.required_executor_skills).toEqual(["alpha"])
  expect(getSkillMode(next, "alpha", false)).toBe("required")
})

test("turns a required individual skill off", () => {
  const next = setSkillMode(
    { executor_skills: [], required_executor_skills: ["alpha"] },
    "alpha",
    "off",
    false,
  )
  expect(next.executor_skills).toEqual([])
  expect(next.required_executor_skills).toEqual([])
  expect(getSkillMode(next, "alpha", false)).toBe("off")
})

test("returns a required group member to available", () => {
  const next = setSkillMode(
    { executor_skills: [], required_executor_skills: ["alpha"] },
    "alpha",
    "available",
    true,
  )
  expect(next.executor_skills).toEqual([])
  expect(next.required_executor_skills).toEqual([])
  expect(getSkillMode(next, "alpha", true)).toBe("available")
})
