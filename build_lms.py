#!/usr/bin/env python3
"""
Reads all markdown study materials and generates a JSON data bundle
that the LMS app can consume.
"""

import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODULES = [
    {
        "id": "01-go-foundations",
        "title": "Go Foundations",
        "description": "Quick refresher on Go basics, then depth on what matters for backend interviews.",
        "icon": "foundation",
        "lessons": [
            "01-types-and-data-structures.md",
            "02-interfaces-and-polymorphism.md",
            "03-error-handling.md",
            "04-project-structure-and-modules.md",
        ]
    },
    {
        "id": "02-go-concepts",
        "title": "Go Concepts",
        "description": "The features that separate senior Go engineers from everyone else.",
        "icon": "brain",
        "lessons": [
            "01-goroutines-and-channels.md",
            "02-sync-and-mutexes.md",
            "03-context.md",
            "04-generics.md",
            "05-testing-and-benchmarks.md",
            "06-standard-library-essentials.md",
        ]
    },
    {
        "id": "03-microservices",
        "title": "Microservices",
        "description": "Distributed system patterns, implemented in Go.",
        "icon": "network",
        "lessons": [
            "01-service-architecture.md",
            "02-saga-pattern.md",
            "03-outbox-pattern.md",
            "04-resilience-patterns.md",
            "05-cqrs.md",
            "06-observability.md",
            "07-api-design.md",
        ]
    },
    {
        "id": "04-system-design",
        "title": "System Design & Interview",
        "description": "The interview-facing layer — scaling, theory, framework, and behavioral prep.",
        "icon": "rocket",
        "lessons": [
            "01-scaling-patterns.md",
            "02-distributed-systems-theory.md",
            "03-interview-framework.md",
            "04-behavioral-prep.md",
            "05-database-internals.md",
            "06-security-patterns.md",
            "07-containers-orchestration.md",
        ]
    },
]

def extract_title(content):
    """Extract the H1 title from markdown content."""
    match = re.match(r'^#\s+(.+)$', content.strip(), re.MULTILINE)
    if match:
        return match.group(1).strip()
    return "Untitled"

def estimate_read_time(content):
    """Estimate reading time in minutes (200 wpm for technical content)."""
    words = len(content.split())
    return max(5, round(words / 200))

def count_exercises(content):
    """Count exercise blocks."""
    return len(re.findall(r'^## Exercise', content, re.MULTILINE))

def count_interview_questions(content):
    """Count interview corner questions."""
    return len(re.findall(r'\*\*Q:', content))

def build_course_data():
    modules = []
    total_lessons = 0
    total_time = 0

    for mod in MODULES:
        mod_dir = os.path.join(BASE_DIR, mod["id"])
        lessons = []

        for lesson_file in mod["lessons"]:
            filepath = os.path.join(mod_dir, lesson_file)
            with open(filepath, "r") as f:
                content = f.read()

            title = extract_title(content)
            read_time = estimate_read_time(content)
            exercises = count_exercises(content)
            interview_qs = count_interview_questions(content)

            lessons.append({
                "id": lesson_file.replace(".md", ""),
                "file": lesson_file,
                "title": title,
                "content": content,
                "readTime": read_time,
                "exercises": exercises,
                "interviewQuestions": interview_qs,
            })
            total_lessons += 1
            total_time += read_time

        modules.append({
            "id": mod["id"],
            "title": mod["title"],
            "description": mod["description"],
            "icon": mod["icon"],
            "lessons": lessons,
        })

    return {
        "course": {
            "title": "Senior Backend Engineer Interview Prep",
            "subtitle": "Go · Microservices · System Design · $200-300K Band",
            "totalLessons": total_lessons,
            "totalTime": total_time,
        },
        "modules": modules,
    }

if __name__ == "__main__":
    data = build_course_data()
    output_path = os.path.join(BASE_DIR, "course_data.json")
    with open(output_path, "w") as f:
        json.dump(data, f)
    print(f"Generated course data: {data['course']['totalLessons']} lessons, ~{data['course']['totalTime']} min total")
    print(f"Output: {output_path}")
