import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = (
    "keller-quote-estimator",
    "keller-quote-register",
    "keller-estimator-evals",
    "polygres",
    "keller-data-analysis",
)


class ArsUmbrisWorkspaceTest(unittest.TestCase):
    def test_entry_identity_and_mount(self):
        repo = (ROOT / ".arsumbris/repo.yaml").read_text()
        workspace = (ROOT / ".arsumbris/workspace.yaml").read_text()
        self.assertIn("name: keller-quotes", repo)
        self.assertIn("type: au.engine.workspace::au-engine", workspace)
        self.assertIn("  - keller-quotes", workspace)
        self.assertIn("  - host-bundle", workspace)
        self.assertIn("  - mcp-bundle", workspace)

    def test_skills_link_to_single_canonical_source(self):
        profile = (ROOT / "profiles/Keller Codex.yaml").read_text()
        self.assertIn("nativeToolAllowlist: []", profile)
        self.assertIn("[[mcp.tool.keller_polygres]]", profile)
        self.assertIn("[[mcp.tool.keller_quote]]", profile)
        self.assertIn("[[mcp.tool.keller_sources]]", profile)
        self.assertIn("[[mcp.tool.au_members::au-mcp-core]]", profile)
        self.assertIn("[[mcp.tool.au_type::au-mcp-core]]", profile)
        for skill in SKILLS:
            source = ROOT / ".agents/skills" / skill / "SKILL.md"
            wrapper = ROOT / "skills" / f"{skill}.md"
            self.assertTrue(source.is_file(), source)
            self.assertTrue(wrapper.is_file(), wrapper)
            text = wrapper.read_text()
            self.assertIn("type: mcp.skill::au-mcp-sdk", text)
            self.assertIn(f"name: {skill}", text)
            self.assertIn(f".agents/skills/{skill}/SKILL.md", text)
            reference = "skills/polygres" if skill == "polygres" else skill
            self.assertIn(f'"[[{reference}]]"', profile)

    def test_narrow_profiles_do_not_grant_shell_or_cross_capabilities(self):
        graph = (ROOT / "profiles/Keller Graph Readonly.yaml").read_text()
        polygres = (ROOT / "profiles/Keller Polygres Readonly.yaml").read_text()
        for profile in (graph, polygres):
            self.assertIn("nativeToolAllowlist: []", profile)
            self.assertIn("skills: []", profile)
            self.assertIn("inject: []", profile)
            self.assertIn("[[mcp.adapter.cc::au-mcp-adapter-cc]]", profile)
        self.assertNotIn("mcp.tool.keller_polygres", graph)
        self.assertNotIn("mcp.tool.keller_quote", graph)
        self.assertNotIn("mcp.tool.keller_sources", graph)
        self.assertIn('  - "[[mcp.tool.keller_polygres]]"', polygres)
        self.assertNotIn("au_members", polygres)
        self.assertNotIn("mcp.tool.keller_quote", polygres)
        self.assertNotIn("mcp.tool.keller_sources", polygres)

    def test_catalog_is_public_pointer_not_private_payload(self):
        entries = tuple((ROOT / "catalog").glob("*.yaml"))
        self.assertEqual(9, len(entries))
        for entry in entries:
            data = entry.read_text()
            self.assertRegex(data, r"\Atype: keller\.(source|organization)\n")
            self.assertNotRegex(data, r"/home/user/|C:\\Vftw\\|postgres(?:ql)?://")
            self.assertFalse(re.search(r"(?:password|secret):", data, re.I))


if __name__ == "__main__":
    unittest.main()
