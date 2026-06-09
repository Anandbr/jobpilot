const {
    Document, Packer, Paragraph, TextRun, AlignmentType,
    LevelFormat, BorderStyle, ExternalHyperlink,
    TabStopType, TabStopPosition
} = require('docx');
const fs = require('fs');

const BLUE = "1F4E79";
const DARK = "1a1a1a";
const MED  = "333333";
const GRAY = "666666";
const FONT = "Arial";

const divider = () => new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 7, color: BLUE, space: 1 } },
    spacing: { before: 100, after: 50 },
    children: []
});

const sectionHeader = (text) => new Paragraph({
    spacing: { before: 100, after: 40 },
    children: [new TextRun({ text, bold: true, size: 20, color: BLUE, font: FONT, allCaps: true })]
});

const bullet = (text) => new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { before: 25, after: 25 },
    children: [new TextRun({ text, size: 18, font: FONT, color: MED })]
});

const subHeader = (text) => new Paragraph({
    spacing: { before: 70, after: 25 },
    children: [new TextRun({ text, bold: true, size: 19, font: FONT, color: DARK })]
});

const skillRow = (category, items) => new Paragraph({
    spacing: { before: 30, after: 30 },
    children: [
        new TextRun({ text: category + ":  ", bold: true, size: 18, font: FONT, color: DARK }),
        new TextRun({ text: items, size: 18, font: FONT, color: MED }),
    ]
});

const jobHeader = (role, company, location, dates) => new Paragraph({
    spacing: { before: 90, after: 25 },
    tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
    children: [
        new TextRun({ text: role, bold: true, size: 20, font: FONT, color: DARK }),
        new TextRun({ text: "  |  ", size: 18, font: FONT, color: "888888" }),
        new TextRun({ text: company, bold: true, size: 19, font: FONT, color: BLUE }),
        new TextRun({ text: "  |  " + location, size: 17, font: FONT, color: GRAY }),
        new TextRun({ text: "\t" + dates, size: 17, font: FONT, color: GRAY, italics: true }),
    ]
});

const projectHeader = (name, tech) => new Paragraph({
    spacing: { before: 70, after: 25 },
    children: [
        new TextRun({ text: name, bold: true, size: 19, font: FONT, color: DARK }),
        new TextRun({ text: "  —  " + tech, size: 17, font: FONT, color: GRAY, italics: true }),
    ]
});

function parseResume(text) {
    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    const result = {
        name: '', title: '', contact: '',
        summary: '', skills: [],
        experience: [], projects: [], education: []
    };

    let section = null;
    let currentJob = null;

    const isBullet = (l) => l.startsWith('•') || l.startsWith('-');
    const isJobLine = (l) =>
        (l.includes('|') && (l.includes('Amazon') || l.includes('Capgemini'))) ||
        (l.includes('Amazon') && l.includes('2022')) ||
        (l.includes('Capgemini') && l.includes('2018'));

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const upper = line.toUpperCase().trim();

        if (i === 0) { result.name = line; continue; }
        if (i === 1) { result.title = line; continue; }
        if (i === 2 && line.includes('@')) { result.contact = line; continue; }

        if (upper === 'PROFESSIONAL SUMMARY') { section = 'summary'; continue; }
        if (upper === 'TECHNICAL SKILLS')     { section = 'skills';  continue; }
        if (upper === 'WORK EXPERIENCE')      { section = 'experience'; currentJob = null; continue; }
        if (upper === 'PORTFOLIO PROJECTS')   { section = 'projects'; currentJob = null; continue; }
        if (upper === 'EDUCATION')            { section = 'education'; continue; }

        if (section === 'summary') {
            result.summary += (result.summary ? ' ' : '') + line;
        }
        else if (section === 'skills') {
            if (line.includes(':')) {
                const idx = line.indexOf(':');
                result.skills.push({
                    category: line.substring(0, idx).trim(),
                    items: line.substring(idx + 1).trim()
                });
            }
        }
        else if (section === 'experience') {
            if (isJobLine(line)) {
                const parts = line.split('|').map(p => p.trim());
                currentJob = {
                    role: parts[0] || '',
                    company: parts[1] || '',
                    locationDate: parts[2] || '',
                    dates: parts[3] || '',
                    sections: [],
                    currentSub: null,
                    defaultBullets: []
                };
                result.experience.push(currentJob);
            } else if (currentJob && isBullet(line)) {
                const b = line.replace(/^[•\-]\s*/, '').trim();
                if (currentJob.currentSub) {
                    currentJob.currentSub.bullets.push(b);
                } else {
                    currentJob.defaultBullets.push(b);
                }
            } else if (currentJob && line.length > 3 && !isBullet(line)) {
                currentJob.currentSub = { title: line, bullets: [] };
                currentJob.sections.push(currentJob.currentSub);
            }
        }
        else if (section === 'projects') {
            if (line.includes('—') || line.includes('–')) {
                const parts = line.split(/—|–/);
                currentJob = { name: parts[0].trim(), tech: (parts[1]||'').trim(), bullets: [] };
                result.projects.push(currentJob);
            } else if (currentJob && isBullet(line)) {
                currentJob.bullets.push(line.replace(/^[•\-]\s*/, '').trim());
            }
        }
        else if (section === 'education') {
            if (line.length > 5) result.education.push(line);
        }
    }
    return result;
}

function buildDocument(parsed) {
    const children = [];

    children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 25 },
        children: [new TextRun({ text: parsed.name, bold: true, size: 34, font: FONT, color: BLUE })]
    }));

    if (parsed.title) {
        children.push(new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 0, after: 25 },
            children: [new TextRun({ text: parsed.title, size: 19, font: FONT, color: GRAY })]
        }));
    }

    if (parsed.contact) {
        const parts = parsed.contact.split('|').map(p => p.trim());
        const runs = [];
        parts.forEach((part, idx) => {
            if (part.includes('linkedin.com')) {
                runs.push(new ExternalHyperlink({
                    link: 'https://' + part.trim(),
                    children: [new TextRun({ text: part.trim(), size: 17, font: FONT, color: BLUE, underline: {} })]
                }));
            } else {
                runs.push(new TextRun({ text: part, size: 17, font: FONT, color: GRAY }));
            }
            if (idx < parts.length - 1) {
                runs.push(new TextRun({ text: '  |  ', size: 17, font: FONT, color: "aaaaaa" }));
            }
        });
        children.push(new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 0, after: 25 },
            children: runs
        }));
    }

    if (parsed.summary) {
        children.push(divider());
        children.push(sectionHeader("Professional Summary"));
        children.push(new Paragraph({
            spacing: { before: 35, after: 35 },
            children: [new TextRun({ text: parsed.summary, size: 18, font: FONT, color: MED })]
        }));
    }

    if (parsed.skills.length > 0) {
        children.push(divider());
        children.push(sectionHeader("Technical Skills"));
        parsed.skills.forEach(s => children.push(skillRow(s.category, s.items)));
    }

    if (parsed.experience.length > 0) {
        children.push(divider());
        children.push(sectionHeader("Work Experience"));
        parsed.experience.forEach(job => {
            children.push(jobHeader(job.role, job.company, job.locationDate, job.dates));
            if (job.sections && job.sections.length > 0) {
                job.sections.forEach(sub => {
                    children.push(subHeader(sub.title));
                    sub.bullets.forEach(b => children.push(bullet(b)));
                });
            }
            if (job.defaultBullets && job.defaultBullets.length > 0) {
                job.defaultBullets.forEach(b => children.push(bullet(b)));
            }
        });
    }

    if (parsed.projects.length > 0) {
        children.push(divider());
        children.push(sectionHeader("Portfolio Projects"));
        parsed.projects.forEach(proj => {
            children.push(projectHeader(proj.name, proj.tech));
            proj.bullets.forEach(b => children.push(bullet(b)));
        });
    }

    if (parsed.education.length > 0) {
        children.push(divider());
        children.push(sectionHeader("Education"));
        parsed.education.forEach(line => {
            const parts = line.split('|').map(p => p.trim());
            if (parts.length >= 2) {
                children.push(new Paragraph({
                    spacing: { before: 50, after: 25 },
                    tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
                    children: [
                        new TextRun({ text: parts[0], bold: true, size: 18, font: FONT, color: DARK }),
                        new TextRun({ text: "  |  " + parts.slice(1).join('  |  '), size: 17, font: FONT, color: GRAY, italics: true }),
                    ]
                }));
            } else {
                children.push(new Paragraph({
                    spacing: { before: 30, after: 25 },
                    children: [new TextRun({ text: line, size: 18, font: FONT, color: MED })]
                }));
            }
        });
    }

    return new Document({
        numbering: {
            config: [{
                reference: "bullets",
                levels: [{
                    level: 0,
                    format: LevelFormat.BULLET,
                    text: "\u2022",
                    alignment: AlignmentType.LEFT,
                    style: { paragraph: { indent: { left: 460, hanging: 230 } } }
                }]
            }]
        },
        sections: [{
            properties: {
                page: {
                    size: { width: 12240, height: 15840 },
                    margin: { top: 750, right: 950, bottom: 750, left: 950 }
                }
            },
            children
        }]
    });
}

async function main() {
    const inputPath  = process.argv[2];
    const outputPath = process.argv[3];
    if (!inputPath || !outputPath) {
        console.error('Usage: node generate_resume.js <input.txt> <output.docx>');
        process.exit(1);
    }
    if (!fs.existsSync(inputPath)) {
        console.error(`Input not found: ${inputPath}`);
        process.exit(1);
    }
    const text   = fs.readFileSync(inputPath, 'utf8');
    const parsed = parseResume(text);
    const doc    = buildDocument(parsed);
    const buffer = await Packer.toBuffer(doc);
    fs.writeFileSync(outputPath, buffer);
    console.log(`Resume generated: ${outputPath}`);
}

main().catch(err => { console.error('Error:', err); process.exit(1); });