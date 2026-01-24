#!/usr/bin/env python3
"""
AgentSkills.io specification validation CLI tool.

Validates skills against the AgentSkills.io specification.

Usage:
    python -m src.cli.skill_validate ./path/to/skill-dir
    python -m src.cli.skill_validate --strict ./path/to/skill-dir
    python -m src.cli.skill_validate --all ./path/to/skills-dir

Examples:
    # Validate a single skill
    python -m src.cli.skill_validate ./src/builtin/skills/code-review

    # Validate all skills in a directory
    python -m src.cli.skill_validate --all ./src/builtin/skills

    # Strict mode (warnings treated as errors)
    python -m src.cli.skill_validate --strict ./src/builtin/skills/code-review
"""

import argparse
import sys
from pathlib import Path

from src.infrastructure.skill.validator import AgentSkillsValidator

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def validate_single(skill_path: Path, strict: bool = False) -> bool:
    """
    Validate a single skill directory.

    Args:
        skill_path: Path to skill directory
        strict: Whether to treat warnings as errors

    Returns:
        True if validation passed
    """
    validator = AgentSkillsValidator(strict=strict)
    result = validator.validate_file(skill_path)

    print(f"\n{'=' * 60}")
    print(f"Skill: {skill_path.name}")
    print(f"{'=' * 60}")
    print(result.format())

    return result.is_valid


def validate_all(skills_dir: Path, strict: bool = False) -> tuple[int, int, int]:
    """
    Validate all skills in a directory.

    Args:
        skills_dir: Directory containing skill subdirectories
        strict: Whether to treat warnings as errors

    Returns:
        Tuple of (passed, failed, skipped)
    """
    passed = 0
    failed = 0
    skipped = 0

    validator = AgentSkillsValidator(strict=strict)

    # Find all SKILL.md files
    skill_dirs = []
    for item in skills_dir.iterdir():
        if item.is_dir() and (item / "SKILL.md").exists():
            skill_dirs.append(item)

    if not skill_dirs:
        print(f"No skills found in {skills_dir}")
        return 0, 0, 0

    print(f"\nFound {len(skill_dirs)} skills to validate\n")

    for skill_dir in sorted(skill_dirs):
        result = validator.validate_file(skill_dir)

        status = "PASS" if result.is_valid else "FAIL"
        status_emoji = "✓" if result.is_valid else "✗"

        print(f"  {status_emoji} [{status}] {skill_dir.name}")

        if result.has_errors:
            for err in result.errors:
                print(f"      Error: [{err.field}] {err.message}")
            failed += 1
        elif result.has_warnings and strict:
            for warn in result.warnings:
                print(f"      Warning: [{warn.field}] {warn.message}")
            failed += 1
        elif result.has_warnings:
            for warn in result.warnings:
                print(f"      Warning: [{warn.field}] {warn.message}")
            passed += 1
        else:
            passed += 1

    return passed, failed, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Validate skills against AgentSkills.io specification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ./src/builtin/skills/code-review
  %(prog)s --all ./src/builtin/skills
  %(prog)s --strict ./src/builtin/skills/code-review
        """,
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to skill directory (or parent directory with --all)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode (treat warnings as errors)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all skills in directory",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode (only show summary)",
    )

    args = parser.parse_args()

    if not args.path.exists():
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)

    print("AgentSkills.io Specification Validator")
    print(f"Mode: {'Strict' if args.strict else 'Normal'}")

    if args.all:
        # Validate all skills in directory
        if not args.path.is_dir():
            print(f"Error: {args.path} is not a directory")
            sys.exit(1)

        passed, failed, skipped = validate_all(args.path, args.strict)

        print(f"\n{'=' * 60}")
        print("Summary:")
        print(f"  Passed:  {passed}")
        print(f"  Failed:  {failed}")
        print(f"  Skipped: {skipped}")
        print(f"{'=' * 60}")

        sys.exit(0 if failed == 0 else 1)
    else:
        # Validate single skill
        if not args.path.is_dir():
            print(f"Error: {args.path} is not a directory")
            sys.exit(1)

        skill_md = args.path / "SKILL.md"
        if not skill_md.exists():
            print(f"Error: SKILL.md not found in {args.path}")
            sys.exit(1)

        is_valid = validate_single(args.path, args.strict)
        sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
