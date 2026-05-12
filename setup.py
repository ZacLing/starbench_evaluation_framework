from setuptools import find_packages, setup


setup(
    name="starbench-evaluation-framework",
    version="0.1.0",
    description="A Docker-backed Codex execution and GPT rubric judging framework.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    package_data={"starbench.runner": ["schemas/*.json"]},
    python_requires=">=3.9",
    install_requires=["tqdm>=4.66"],
    entry_points={"console_scripts": ["starbench-run=starbench.runner.run_benchmark:main"]},
)
