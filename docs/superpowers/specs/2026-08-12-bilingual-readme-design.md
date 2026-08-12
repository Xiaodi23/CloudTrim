# Bilingual README Design

## Goal

Provide complete Chinese and English project introductions that are easy to switch between and remain consistent as LasTool evolves.

## File Structure

- `README.md` is the default Simplified Chinese landing page.
- `README_EN.md` is the complete English version.
- Both files begin with visible language links: `简体中文 | English`.

This two-file structure keeps each document readable while making the alternative language one click away. It is preferred over placing two long documents in one file or alternating languages paragraph by paragraph.

## Shared Content

Both files use the same section order and communicate the same facts:

1. Project summary and local-processing focus.
2. GitHub Actions status, latest release, license, and platform badges.
3. Direct Windows portable ZIP download and release-page links.
4. Features and supported processing modes.
5. Portable usage and source installation.
6. Output naming rules.
7. Portable build and test commands.
8. Current limitations, privacy statement, and license.

The Chinese text will be natural Chinese documentation rather than a word-for-word translation. Commands, filenames, links, version numbers, and technical behavior remain identical between languages.

## Release Behavior

This documentation-only update does not create a new application release tag because the executable and processing behavior do not change. The updated README files will be committed to `main` and pushed to GitHub. The existing `v0.1.0` portable download remains the recommended binary.

## Verification

- Check that both language-switch links resolve to files in the repository.
- Check that both documents contain the same current release download URL.
- Check Markdown formatting and repository-relative links.
- Run the existing unit tests to confirm the documentation-only commit does not disturb the project.
- Verify the pushed `main` commit matches the local commit.
