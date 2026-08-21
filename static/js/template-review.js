// static/js/template-review.js - Template-based review UI (mTool style)

export class TemplateReviewManager {
    constructor(api) {
        this.api = api;
        this.currentJobId = null;
        this.currentStatement = null;
        this.templates = {};
        this.extractedData = {};
        this.unsavedChanges = new Map();
        this.scrollPositions = {}; // Track scroll position for each statement
    }

    /**
     * Initialize template review for a job
     */
    async initialize(jobId) {
        this.currentJobId = jobId;

        // Load available statements
        await this.loadStatements();

        // Render statement selector
        this.renderStatementSelector();

        // Auto-select first statement (Filing Information - 010000)
        if (this.statements && this.statements.length > 0) {
            // Find the statement with the lowest code (010000 - Filing Information)
            const sortedStatements = [...this.statements].sort((a, b) => {
                const codeA = a.statement_code || a.code || '999999';
                const codeB = b.statement_code || b.code || '999999';
                return codeA.localeCompare(codeB);
            });

            const firstStatement = sortedStatements[0];
            if (firstStatement) {
                const firstCode = firstStatement.statement_code || firstStatement.code;
                const firstType = firstStatement.statement_type || firstStatement.type;
                console.log(`🎯 Auto-loading first statement: ${firstCode} - ${firstType}`);
                await this.loadStatement(firstCode);
            }
        }
    }

    /**
     * Load all available statements
     */
    async loadStatements() {
        try {
            // Use XBRL templates API
            const response = await fetch('/api/v1/xbrl-templates/');

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            console.log('📥 Loaded XBRL templates:', data);

            // API returns array directly, not {templates: [...]}
            if (Array.isArray(data)) {
                // Convert XBRL template format to expected format
                this.statements = data.map(t => ({
                    code: t.code,
                    statement_code: t.code,
                    statement_type: t.description,
                    type: t.description,
                    total_fields: t.total_concepts
                }));
                console.log(`✅ Converted ${this.statements.length} templates`);
                return this.statements;
            } else {
                console.error('❌ Response is not an array:', data);
                this.statements = [];
            }
        } catch (error) {
            console.error('❌ Error loading statements:', error);
            this.statements = [];
        }
        return this.statements || [];
    }

    /**
     * Render statement selector buttons
     */
    renderStatementSelector() {
        const container = document.getElementById('statement-selector');
        if (!container) {
            console.error('❌ Statement selector container not found!');
            return;
        }

        console.log('🎨 Rendering statement selector. Current statement:', this.currentStatement?.statement_code);

        const sortedStatements = [...this.statements].sort((a, b) => {
            const codeA = a.statement_code || a.code || '999999';
            const codeB = b.statement_code || b.code || '999999';
            return codeA.localeCompare(codeB);
        });

        // Store current scroll position before re-rendering
        const scrollContainer = container.querySelector('.overflow-x-auto');
        let savedScrollLeft = 0;
        if (scrollContainer) {
            savedScrollLeft = scrollContainer.scrollLeft;
        }

        // FIXED: Better horizontal scroll with contained width
        let html = `
            <div class="relative bg-gray-50 rounded-xl p-4 border border-gray-200">
                <div class="text-xs font-semibold text-gray-600 uppercase mb-3">Select Statement Type</div>
                <!-- Horizontal scroll with max-width constraint -->
                <div class="overflow-x-auto pb-2 scrollbar-thin statement-scroll-container" style="max-width: calc(100vw - 380px);" id="statement-scroll">
                    <div class="flex gap-3 min-w-max">
        `;

        for (const stmt of sortedStatements) {
            const stmtCode = stmt.statement_code || stmt.code;
            const currentCode = this.currentStatement?.statement_code || this.currentStatement?.code;
            const isActive = currentCode === stmtCode;

            if (isActive) {
                console.log(`✅ Statement ${stmtCode} is ACTIVE - applying highlight styles`);
            }

            const activeClass = isActive
                ? 'bg-gradient-to-r from-blue-600 to-blue-700 text-white border-blue-800 shadow-2xl ring-4 ring-blue-400 ring-offset-2'
                : 'bg-white text-gray-700 hover:bg-blue-50 border-gray-300 hover:border-blue-400 hover:shadow-md';

            // Add a very strong visual indicator for active state
            // const activeIndicator = isActive
            //     ? `<div class="absolute -top-1 -right-1 bg-green-500 rounded-full p-1 shadow-lg ring-2 ring-white">
            //         <svg class="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
            //             <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"/>
            //         </svg>
            //     </div>`
            //     : '';

            html += `
                <button
                    class="statement-btn relative flex-shrink-0 px-4 py-3 rounded-lg border-2 ${activeClass} font-semibold transition-all transform ${isActive ? 'scale-110' : 'hover:scale-102'}"
                    style="min-width: 140px; max-width: 180px;"
                    data-code="${stmtCode}"
                    title="FS-MPERS statement ${stmtCode}: ${stmt.statement_type || stmt.type || stmtCode}"
                    onclick="window.templateReview.loadStatement('${stmtCode}')">
                    
                    <div class="flex items-center justify-between mb-1">
                        <div class="text-xs font-mono ${isActive ? 'text-blue-100 font-bold' : 'text-gray-500'}">${stmtCode}</div>
                        ${isActive ? '<svg class="w-4 h-4 text-green-300 animate-pulse" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"/></svg>' : ''}
                    </div>
                    <div class="text-sm font-semibold leading-tight mb-1 ${isActive ? 'text-white' : ''}">${this._truncateText(stmt.statement_type || stmt.type, 28)}</div>
                    <div class="text-xs ${isActive ? 'text-blue-100' : 'text-gray-500'} flex items-center gap-1">
                        <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z"/><path fill-rule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"/></svg>
                        ${stmt.total_fields} fields
                    </div>
                </button>
            `;
        }

        html += `
                    </div>
                </div>
                <!-- Scroll hint -->
                <div class="text-xs text-gray-400 text-center mt-2">
                    ${this.currentStatement ? `<span class="text-blue-600 font-semibold">Selected: ${this.currentStatement.statement_code || this.currentStatement.code} - ${this.currentStatement.title || this.currentStatement.description || 'Unknown statement'}</span> • ` : ''}FS-MPERS statement codes • Scroll horizontally to view all statements
                </div>
            </div>
        `;

        container.innerHTML = html;

        // Restore scroll position after re-rendering
        const newScrollContainer = document.getElementById('statement-scroll');
        if (newScrollContainer && savedScrollLeft > 0) {
            setTimeout(() => {
                newScrollContainer.scrollLeft = savedScrollLeft;
            }, 10);
        }

        // If there's a current statement, scroll it into view
        if (this.currentStatement && newScrollContainer) {
            setTimeout(() => {
                const currentCode = this.currentStatement.statement_code || this.currentStatement.code;
                const activeBtn = newScrollContainer.querySelector(`[data-code="${currentCode}"]`);
                if (activeBtn) {
                    activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
                }
            }, 50);
        }
    }

    /**
     * Truncate text helper
     */
    _truncateText(text, maxLength) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength - 3) + '...';
    }

    /**
     * Load and display a specific statement
     */
    async loadStatement(statementCode) {
        try {
            console.log(`📥 Loading statement: ${statementCode}`);

            // Load template structure using XBRL templates API
            const templateResponse = await fetch(`/api/v1/xbrl-templates/${statementCode}`);
            const templateData = await templateResponse.json();

            // API returns template object directly (TemplateDetailResponse)
            if (!templateData || !templateData.concepts) {
                throw new Error('Failed to load template');
            }

            console.log(`✅ Template loaded successfully:`, templateData);

            let statement = templateData;

            // Convert XBRL concepts to XML-style sections/groups structure if needed
            if (statement.concepts && !statement.sections) {
                console.log('🔄 Converting XBRL concepts to XML-style structure...');
                statement = this._convertXBRLToXMLStructure(statement);
            }

            this.currentStatement = statement;
            this.templates[statementCode] = statement;

            console.log(`✅ currentStatement set to:`, this.currentStatement.statement_code);

            // Update UI
            this.renderStatementSelector();
            this.renderTemplate(this.currentStatement);

            // Load extracted data and populate fields
            await this.loadAndPopulateExtractedData(statementCode);

        } catch (error) {
            console.error('❌ Error loading statement:', error);
            this.showNotification('Error loading statement template', 'error');
        }
    }

    /**
     * Convert XBRL concepts (flat array) to XML-style structure (with sections/groups)
     */
    _convertXBRLToXMLStructure(statement) {
        // XBRL concepts are already flat with all metadata
        // For now, create a simple single-section structure
        const concepts = statement.concepts || [];

        // Group concepts by level for better organization
        const sections = [{
            id: 'main',
            title: statement.description || 'Financial Data',
            description: '',
            groups: [],
            fields: concepts.map(c => ({
                id: c.id,
                label: c.label,
                required: c.required || false,
                data_type: this._inferDataType(c.id),
                xbrl_tag: c.id,
                level: c.level || 0,
                parent: c.parent || '',
                description: ''
            }))
        }];

        return {
            ...statement,
            code: statement.code,
            statement_code: statement.code,
            title: statement.description,
            description: `FS-MPERS statement code ${statement.code}`,
            sections: sections
        };
    }

    /**
     * Infer data type from XBRL concept ID
     */
    _inferDataType(conceptId) {
        const lower = conceptId.toLowerCase();
        if (lower.includes('date')) return 'date';
        if (lower.includes('assets') || lower.includes('liabilities') ||
            lower.includes('equity') || lower.includes('revenue') ||
            lower.includes('amount') || lower.includes('cash')) return 'monetary';
        if (lower.includes('description') || lower.includes('disclosure')) return 'text-block';
        if (lower.includes('percentage') || lower.includes('rate')) return 'string';
        if (lower.includes('shares') || lower.includes('units')) return 'integer';
        return 'string';
    }

    /**
     * Recursively build a group from a field and its children
     */
    _buildGroupFromField(field, allFields) {
        const group = {
            id: field.id,
            title: field.label,
            level: field.level,
            fields: [],
            nested_groups: [],
            subgroups: []
        };

        // Get direct children of this field
        const children = allFields.filter(f => f.parent === field.id);

        for (const child of children) {
            if (child.is_abstract) {
                // Abstract child = nested group
                const nestedGroup = this._buildGroupFromField(child, allFields);
                group.nested_groups.push(nestedGroup);
            } else {
                // Concrete child = field
                group.fields.push(child);
            }
        }

        return group;
    }

    /**
     * Render the template structure
     */
    renderTemplate(statement) {
        const container = document.getElementById('template-container');
        if (!container) return;

        let html = `
            <div class="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                <!-- Statement Header -->
                <div class="bg-gradient-to-r from-blue-50 to-indigo-50 p-6 border-b border-gray-200">
                    <h2 class="text-2xl font-bold text-gray-900">${statement.title}</h2>
                    <p class="text-sm text-gray-600 mt-2">${statement.description}</p>
                </div>

                <!-- Sections -->
                <div class="p-6 space-y-6">
        `;

        // Render each section
        for (const section of statement.sections) {
            html += this.renderSection(section);
        }

        html += `
                </div>
            </div>
        `;

        container.innerHTML = html;

        // Initialize interactive features
        this.initializeFieldHandlers();
    }

    /**
     * Render a section
     */
    renderSection(section) {
        const sectionId = `section-${section.id}`;

        let html = `
            <div class="section bg-gray-50 rounded-lg border border-gray-200 overflow-hidden">
                <!-- Section Header -->
                <div class="section-header bg-gradient-to-r from-gray-100 to-gray-50 p-4 cursor-pointer hover:bg-gray-100 transition-colors"
                     onclick="this.parentElement.querySelector('.section-body').classList.toggle('hidden')">
                    <div class="flex items-center justify-between">
                        <h3 class="text-lg font-semibold text-gray-900">${section.title}</h3>
                        <svg class="w-5 h-5 text-gray-400 transform transition-transform" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"/>
                        </svg>
                    </div>
                </div>

                <!-- Section Body -->
                <div class="section-body p-6 bg-white space-y-6" id="${sectionId}">
        `;

        // Render groups (check if groups array exists and has items)
        if (section.groups && section.groups.length > 0) {
            for (const group of section.groups) {
                html += this.renderGroup(group);
            }
        }

        // Render direct fields (if any)
        if (section.fields && section.fields.length > 0) {
            html += '<div class="space-y-4">';
            for (const field of section.fields) {
                html += this.renderField(field);
            }
            html += '</div>';
        }

        html += `
                </div>
            </div>
        `;

        return html;
    }

    /**
     * Render a group (with recursive nested group support and visual hierarchy)
     */
    renderGroup(group) {
        // Calculate indentation based on level (each level adds 1rem padding)
        const level = parseInt(group.level) || 2;
        const indent = Math.max(0, (level - 2)) * 1.5; // Start indent from level 3
        const indentStyle = indent > 0 ? `style="padding-left: ${indent}rem;"` : '';

        // Adjust border color intensity based on level (deeper = lighter)
        const borderColors = ['border-blue-400', 'border-blue-300', 'border-gray-300', 'border-gray-200'];
        const borderColor = borderColors[Math.min(level - 2, borderColors.length - 1)] || 'border-gray-200';

        let html = `
            <div class="group border-l-4 ${borderColor} pl-6 py-4" ${indentStyle}>
                <h4 class="text-md font-semibold text-gray-800 mb-4">${group.title}</h4>
                <div class="space-y-4">
        `;

        // Render fields in this group
        if (group.fields && group.fields.length > 0) {
            for (const field of group.fields) {
                html += this.renderField(field);
            }
        }

        // Render nested groups (RECURSIVE - handles deep nesting like 210000)
        if (group.nested_groups && group.nested_groups.length > 0) {
            for (const nestedGroup of group.nested_groups) {
                html += this.renderGroup(nestedGroup);  // Recursive call
            }
        }

        // Render subgroups
        if (group.subgroups && group.subgroups.length > 0) {
            for (const subgroup of group.subgroups) {
                html += this.renderSubgroup(subgroup);
            }
        }

        // Render tables
        if (group.tables && group.tables.length > 0) {
            for (const table of group.tables) {
                html += this.renderTable(table);
            }
        }

        html += `
                </div>
            </div>
        `;

        return html;
    }

    /**
     * Render a subgroup
     */
    renderSubgroup(subgroup) {
        let html = `
            <div class="subgroup border-l-2 border-gray-300 pl-4 py-2">
                <h5 class="text-sm font-semibold text-gray-700 mb-3">${subgroup.title}</h5>
                <div class="space-y-3">
        `;

        for (const field of subgroup.fields) {
            html += this.renderField(field);
        }

        html += `
                </div>
            </div>
        `;

        return html;
    }

    /**
     * Render a single field based on its data type
     */
    renderField(field) {
        const requiredMark = field.required ? '<span class="text-red-500">*</span>' : '';
        const fieldId = field.id;
        const sampleValue = field.sample_value || '';
        const hasComparative = field.comparative === 'true' || field.comparative === true;

        let inputHtml = '';

        // For comparative fields (monetary with instant period), render two columns
        if (hasComparative && field.data_type === 'monetary') {
            inputHtml = `
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">Current Year</label>
                        <input type="text"
                               id="${fieldId}_current"
                               data-field-id="${fieldId}"
                               data-period="current"
                               class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                               placeholder="${sampleValue}"
                               value="">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-gray-600 mb-1">Previous Year</label>
                        <input type="text"
                               id="${fieldId}_comparative"
                               data-field-id="${fieldId}"
                               data-period="comparative"
                               class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                               placeholder="${sampleValue}"
                               value="">
                    </div>
                </div>
            `;
        } else {
            // Render based on data type (single field)
            switch (field.data_type) {
                case 'date':
                    inputHtml = `
                        <input type="text"
                               id="${fieldId}"
                               data-field-id="${fieldId}"
                               class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                               placeholder="${sampleValue || 'DD/MM/YYYY'}"
                               value="">
                    `;
                    break;

                case 'dropdown':
                    const allowedValues = field.validation?.allowed_values || [];
                    inputHtml = `
                        <select id="${fieldId}"
                                data-field-id="${fieldId}"
                                class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                            <option value="">-- Select --</option>
                            ${allowedValues.map(val => `<option value="${val}">${val}</option>`).join('')}
                        </select>
                    `;
                    break;

                case 'integer':
                    inputHtml = `
                        <input type="number"
                               id="${fieldId}"
                               data-field-id="${fieldId}"
                               class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                               placeholder="${sampleValue}"
                               value="">
                    `;
                    break;

                case 'text-block':
                    inputHtml = `
                        <textarea id="${fieldId}"
                                  data-field-id="${fieldId}"
                                  rows="4"
                                  class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                  placeholder="${sampleValue}"></textarea>
                    `;
                    break;

                default: // string and others
                    const maxLength = field.max_length ? `maxlength="${field.max_length}"` : '';
                    inputHtml = `
                        <input type="text"
                               id="${fieldId}"
                               data-field-id="${fieldId}"
                               class="field-input w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                               placeholder="${sampleValue}"
                               ${maxLength}
                               value="">
                    `;
            }
        }

        return `
            <div class="field-container" data-field-id="${fieldId}">
                <label class="block text-sm font-medium text-gray-700 mb-2">
                    ${requiredMark} ${field.label}
                </label>
                ${inputHtml}
                ${field.description ? `<p class="text-xs text-gray-500 mt-1">${field.description}</p>` : ''}
            </div>
        `;
    }

    /**
     * Render a table
     */
    renderTable(table) {
        const tableId = table.id;

        let html = `
            <div class="table-container border border-gray-300 rounded-lg overflow-hidden">
                <div class="bg-gray-100 px-4 py-3 border-b border-gray-300">
                    <h5 class="font-semibold text-gray-800">${table.label}</h5>
                    ${table.description ? `<p class="text-xs text-gray-600 mt-1">${table.description}</p>` : ''}
                </div>

                <table class="w-full" id="${tableId}">
                    <thead class="bg-gray-50">
                        <tr>
                            ${table.columns.map(col => `
                                <th class="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">
                                    ${col.required ? '<span class="text-red-500">*</span>' : ''} ${col.label}
                                </th>
                            `).join('')}
                            <th class="px-4 py-3 w-16"></th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200">
        `;

        // Render rows
        for (const row of table.rows) {
            if (!row.required) continue; // Skip optional rows initially

            html += `<tr data-row-id="${row.id}">`;

            for (const col of table.columns) {
                const sampleVal = row.sample_values.find(sv => sv.column === col.id)?.value || '';
                const cellId = `${tableId}_${row.id}_${col.id}`;

                html += `
                    <td class="px-4 py-3">
                        <input type="text"
                               id="${cellId}"
                               data-table-id="${tableId}"
                               data-row-id="${row.id}"
                               data-col-id="${col.id}"
                               class="table-cell-input w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500"
                               placeholder="${sampleVal}"
                               value="${sampleVal}">
                    </td>
                `;
            }

            html += `
                    <td class="px-4 py-3 text-center">
                        <button class="text-gray-400 hover:text-red-600" title="${row.label}">
                            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"/>
                            </svg>
                        </button>
                    </td>
                </tr>
            `;
        }

        html += `
                    </tbody>
                </table>
            </div>
        `;

        return html;
    }

    /**
     * Initialize field change handlers
     */
    initializeFieldHandlers() {
        // Track changes on all field inputs
        document.querySelectorAll('.field-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const fieldId = e.target.dataset.fieldId;
                const value = e.target.value;

                this.unsavedChanges.set(fieldId, value);
                this.showUnsavedIndicator();
            });
        });

        // Track changes on table cells
        document.querySelectorAll('.table-cell-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const tableId = e.target.dataset.tableId;
                const rowId = e.target.dataset.rowId;
                const colId = e.target.dataset.colId;
                const cellKey = `${tableId}_${rowId}_${colId}`;

                this.unsavedChanges.set(cellKey, e.target.value);
                this.showUnsavedIndicator();
            });
        });

        // Global click handler to close multi-value dropdowns when clicking outside
        // Remove old handler if exists to prevent duplicates
        if (this.globalClickHandler) {
            document.removeEventListener('click', this.globalClickHandler);
        }

        this.globalClickHandler = (e) => {
            // Check if click is outside all multi-value dropdowns
            const clickedInsideDropdown = e.target.closest('.multi-value-dropdown, button[type="button"]');
            if (!clickedInsideDropdown) {
                document.querySelectorAll('.multi-value-dropdown').forEach(d => {
                    d.classList.add('hidden');
                });
            }
        };

        document.addEventListener('click', this.globalClickHandler);
    }

    /**
     * Show unsaved changes indicator
     */
    showUnsavedIndicator() {
        const indicator = document.getElementById('unsaved-indicator');
        if (indicator) {
            indicator.classList.remove('hidden');
            indicator.textContent = `${this.unsavedChanges.size} unsaved change(s)`;
        }
    }

    /**
     * Save all changes
     */
    async saveChanges() {
        try {
            console.log('💾 Saving changes:', this.unsavedChanges);

            // Collect all field updates from the DOM
            const updates = [];
            const newItems = [];

            // Get all input fields in the current template
            const inputFields = document.querySelectorAll('input[data-field-id], textarea[data-field-id], select[data-field-id]');

            for (const field of inputFields) {
                const fieldId = field.dataset.fieldId;
                const period = field.dataset.period; // current or comparative
                const value = field.value;

                // Only save fields that have values or were changed
                if (!value || value.trim() === '') continue;

                // Find matching extracted data item(s) for this template field
                const matchingItems = this.findExtractedItemsForField(fieldId, period);

                if (matchingItems.length > 0) {
                    // Update existing items
                    for (const item of matchingItems) {
                        updates.push({
                            id: item.id,
                            extracted_value: value,
                            template_field_id: fieldId,
                            is_reviewed: true // Mark as reviewed when manually edited
                        });
                    }
                } else {
                    // This is a new entry - create it
                    console.log(`📝 Creating new item for field ${fieldId}: "${value}"`);

                    // Get field metadata for label
                    const fieldMetadata = this.getFieldMetadata(fieldId);
                    const fieldLabel = fieldMetadata ? fieldMetadata.label : fieldId;

                    newItems.push({
                        template_field_id: fieldId,
                        extracted_label: fieldLabel,
                        extracted_value: value,
                        financial_year: new Date().getFullYear(), // Default to current year
                        is_reviewed: true,
                        statement_type: this.currentStatement?.statement_type || this.currentStatement?.type || null
                    });
                }
            }

            let totalSaved = 0;

            // Save updates via bulk update API
            if (updates.length > 0) {
                console.log(`📤 Sending ${updates.length} updates to backend...`);
                const response = await this.api.bulkUpdateItems(updates);
                totalSaved += updates.length;
                console.log('✅ Updates saved:', response);
            }

            // Create new items via API
            if (newItems.length > 0) {
                console.log(`📤 Creating ${newItems.length} new items...`);

                // Get the first page ID for this job (we need a page_id to create items)
                const pagesResponse = await this.api.getPages(this.currentJobId);
                if (!pagesResponse || !pagesResponse.length) {
                    throw new Error('No pages found for this job. Cannot create new items.');
                }

                const firstPageId = pagesResponse[0].id;

                for (const newItem of newItems) {
                    try {
                        await this.api.createExtractedDataItem({
                            ...newItem,
                            page_id: firstPageId
                        });
                        totalSaved++;
                    } catch (err) {
                        console.error(`Failed to create item for ${newItem.template_field_id}:`, err);
                    }
                }

                console.log(`✅ Created ${newItems.length} new items`);

                // Reload extracted data to get the newly created items with their IDs
                await this.loadAndPopulateExtractedData(this.currentStatement.code);
            }

            if (updates.length === 0 && newItems.length === 0) {
                this.showNotification('No changes to save', 'info');
            }

            // Clear unsaved changes
            this.unsavedChanges.clear();

            const indicator = document.getElementById('unsaved-indicator');
            if (indicator) {
                indicator.classList.add('hidden');
            }

            if (totalSaved > 0) {
                this.showNotification(`Successfully saved ${totalSaved} change(s)`, 'success');
            }
            return true;

        } catch (error) {
            console.error('❌ Error saving changes:', error);
            this.showNotification(`Error saving changes: ${error.message}`, 'error');
            return false;
        }
    }

    /**
     * Find extracted data items that match a template field
     */
    findExtractedItemsForField(fieldId, period = null) {
        const items = this.extractedData[fieldId] || [];

        if (!period) {
            return items;
        }

        // Filter by period (current = latest year, comparative = previous year)
        if (items.length === 0) return [];

        // Sort by financial year descending
        const sorted = [...items].sort((a, b) => (b.financial_year || 0) - (a.financial_year || 0));

        if (period === 'current') {
            return sorted.length > 0 ? [sorted[0]] : [];
        } else if (period === 'comparative') {
            return sorted.length > 1 ? [sorted[1]] : [];
        }

        return sorted;
    }

    /**
     * Get field metadata from current statement by field ID
     */
    getFieldMetadata(fieldId) {
        if (!this.currentStatement) return null;

        const findFieldRecursive = (obj) => {
            if (obj.id === fieldId) {
                return obj;
            }

            // Check in fields array
            if (obj.fields && Array.isArray(obj.fields)) {
                for (const field of obj.fields) {
                    if (field.id === fieldId) return field;
                }
            }

            // Check in sections
            if (obj.sections && Array.isArray(obj.sections)) {
                for (const section of obj.sections) {
                    const found = findFieldRecursive(section);
                    if (found) return found;
                }
            }

            // Check in groups
            if (obj.groups && Array.isArray(obj.groups)) {
                for (const group of obj.groups) {
                    const found = findFieldRecursive(group);
                    if (found) return found;
                }
            }

            // Check in subgroups
            if (obj.subgroups && Array.isArray(obj.subgroups)) {
                for (const subgroup of obj.subgroups) {
                    const found = findFieldRecursive(subgroup);
                    if (found) return found;
                }
            }

            return null;
        };

        return findFieldRecursive(this.currentStatement);
    }

    /**
     * Find best matching option for dropdown fields using fuzzy matching
     */
    findBestDropdownMatch(extractedValue, allowedValues) {
        if (!extractedValue || !allowedValues || allowedValues.length === 0) {
            return null;
        }

        const normalizedExtracted = extractedValue.toLowerCase().trim();

        // First try exact match (case-insensitive)
        for (const option of allowedValues) {
            if (option.toLowerCase().trim() === normalizedExtracted) {
                return option;
            }
        }

        // Try partial match (extracted value contains option or vice versa)
        for (const option of allowedValues) {
            const normalizedOption = option.toLowerCase().trim();
            if (normalizedExtracted.includes(normalizedOption) || normalizedOption.includes(normalizedExtracted)) {
                return option;
            }
        }

        // Try word-based matching (check if any significant words match)
        const extractedWords = normalizedExtracted.split(/\s+/).filter(w => w.length > 3);
        let bestMatch = null;
        let bestScore = 0;

        for (const option of allowedValues) {
            const optionWords = option.toLowerCase().split(/\s+/).filter(w => w.length > 3);
            let matchCount = 0;

            for (const extractedWord of extractedWords) {
                for (const optionWord of optionWords) {
                    if (extractedWord.includes(optionWord) || optionWord.includes(extractedWord)) {
                        matchCount++;
                    }
                }
            }

            const score = matchCount / Math.max(extractedWords.length, optionWords.length, 1);
            if (score > bestScore && score > 0.3) {
                bestScore = score;
                bestMatch = option;
            }
        }

        return bestMatch;
    }

    /**
     * Populate a field element with extracted value (handles dropdowns, inputs, textareas)
     */
    populateFieldElement(fieldElement, extractedValues, validation = {}) {
        const tagName = fieldElement.tagName.toLowerCase();

        // Handle arrays (multiple extracted values)
        if (Array.isArray(extractedValues)) {
            if (extractedValues.length > 1) {
                // Multiple values - create dropdown selector
                return this._createMultiValueField(fieldElement, extractedValues, validation);
            } else {
                // Single value in array
                extractedValues = extractedValues[0];
            }
        }

        // Original logic for select (validation dropdown)
        if (tagName === 'select') {
            const allowedValues = validation?.allowed_values || [];
            const matchedOption = this.findBestDropdownMatch(extractedValues, allowedValues);

            if (matchedOption) {
                fieldElement.value = matchedOption;
                return { success: true, matched: true, matchedValue: matchedOption };
            } else {
                // Show extracted value in title but don't select
                fieldElement.title = `Extracted: "${extractedValues}" (no matching option)`;
                return { success: false, matched: false, extractedValue: extractedValues };
            }
        } else {
            // Input/textarea - just set value
            fieldElement.value = extractedValues;
            return { success: true, matched: true, matchedValue: extractedValues };
        }
    }


    _createMultiValueField(fieldElement, extractedValues, validation) {
        console.log('🎨 Creating multi-value dropdown for:', fieldElement.id, extractedValues);

        // Get parent container
        const parentContainer = fieldElement.parentElement;
        if (!parentContainer) {
            console.error('❌ No parent container found');
            return { success: false, matched: false };
        }

        // Store original attributes
        const fieldId = fieldElement.dataset.fieldId;
        const fieldPeriod = fieldElement.dataset.period;
        const originalClasses = fieldElement.className;
        const originalPlaceholder = fieldElement.placeholder;

        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'relative w-full';

        // Create new input
        const input = document.createElement('input');
        input.type = 'text';
        input.className = originalClasses + ' pr-10 bg-blue-50 border-blue-400'; // Highlight multi-value fields
        input.dataset.fieldId = fieldId;
        if (fieldPeriod) input.dataset.period = fieldPeriod;
        input.value = extractedValues[0]; // Default to first value
        input.placeholder = originalPlaceholder;

        // Add change listener to track changes
        input.addEventListener('change', (e) => {
            this.unsavedChanges.set(fieldId, e.target.value);
            this.showUnsavedIndicator();
            console.log('📝 Multi-value field changed:', fieldId, e.target.value);
        });

        // Create dropdown toggle button
        const toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'absolute right-2 top-1/2 transform -translate-y-1/2 p-1 text-gray-500 hover:text-blue-600 transition-colors';
        toggleBtn.innerHTML = `
            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"/>
            </svg>
        `;
        toggleBtn.title = `${extractedValues.length} values found - click to select`;

        // Create dropdown menu
        const dropdown = document.createElement('div');
        dropdown.className = 'hidden absolute top-full left-0 right-0 mt-1 bg-white border-2 border-blue-300 rounded-lg shadow-xl z-50 max-h-48 overflow-y-auto';

        // Add options with visual distinction
        extractedValues.forEach((val, idx) => {
            const option = document.createElement('div');
            option.className = 'px-4 py-3 hover:bg-blue-50 cursor-pointer border-b border-gray-100 last:border-b-0 transition-colors';
            option.dataset.value = val;

            const isSelected = idx === 0;
            option.innerHTML = `
                <div class="flex items-center justify-between">
                    <div>
                        <div class="font-medium ${isSelected ? 'text-blue-600' : 'text-gray-800'}">${val}</div>
                        <div class="text-xs text-gray-500">Extracted value ${idx + 1}</div>
                    </div>
                    ${isSelected ? '<svg class="w-5 h-5 text-blue-600" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"/></svg>' : ''}
                </div>
            `;

            // Click handler
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                input.value = val;
                dropdown.classList.add('hidden');

                // Update selection indicator
                dropdown.querySelectorAll('[data-value]').forEach(opt => {
                    const icon = opt.querySelector('svg');
                    const text = opt.querySelector('.font-medium');
                    if (opt.dataset.value === val) {
                        if (icon) icon.classList.remove('hidden');
                        if (text) text.classList.add('text-blue-600');
                    } else {
                        if (icon) icon.classList.add('hidden');
                        if (text) text.classList.remove('text-blue-600');
                    }
                });

                // Trigger change event
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });

            dropdown.appendChild(option);
        });

        // Toggle dropdown
        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault(); // Prevent any default button behavior
            const isHidden = dropdown.classList.contains('hidden');

            // Close all other dropdowns first
            document.querySelectorAll('.multi-value-dropdown').forEach(d => {
                if (d !== dropdown) d.classList.add('hidden');
            });

            dropdown.classList.toggle('hidden', !isHidden);

            console.log('🎯 Dropdown toggled:', isHidden ? 'opened' : 'closed');
        });

        // Mark dropdown for identification
        dropdown.classList.add('multi-value-dropdown');
        dropdown.dataset.fieldId = fieldId; // Store field ID for debugging

        // Assemble wrapper
        wrapper.appendChild(input);
        wrapper.appendChild(toggleBtn);
        wrapper.appendChild(dropdown);

        // Replace original element
        try {
            parentContainer.replaceChild(wrapper, fieldElement);
            console.log('✅ Multi-value field created successfully');
        } catch (err) {
            console.error('❌ Failed to replace field element:', err);
            return { success: false, matched: false };
        }

        return {
            success: true,
            matched: true,
            matchedValue: extractedValues[0],
            multiValue: true,
            allValues: extractedValues
        };
    }

    /**
     * Normalize field ID by stripping XBRL namespace prefix
     * Examples:
     *   "ssmt-dei_CompanyRegistrationNumber" -> "CompanyRegistrationNumber"
     *   "CompanyRegistrationNumber" -> "CompanyRegistrationNumber"
     */
    normalizeFieldId(fieldId) {
        if (!fieldId) return fieldId;

        // Check if it contains underscore (XBRL tag format: namespace_elementName)
        const underscoreIndex = fieldId.indexOf('_');
        if (underscoreIndex > 0) {
            // Strip namespace prefix
            return fieldId.substring(underscoreIndex + 1);
        }

        return fieldId;
    }

    /**
     * Load extracted data from backend and populate fields
     */
    async loadAndPopulateExtractedData(statementCode) {
        if (!this.currentJobId) {
            console.warn('No job ID set');
            return;
        }

        try {
            console.log(`Loading extracted data for job ${this.currentJobId}, statement: ${statementCode}...`);

            // Fetch all extracted data for this job
            const response = await this.api.getExtractedData(this.currentJobId, 1, 1000);

            if (!response || !response.items) {
                console.warn('No extracted data found');
                return;
            }

            // ✅ **FIX:** Filter items that are matched to a template field and assign to matchedItems
            const matchedItems = response.items.filter(i => i.template_field_id);

            console.log(`📊 Found ${response.items.length} extracted items, ${matchedItems.length} matched to templates`);

            // Group by field_id (normalized to strip XBRL namespace)
            const dataByFieldId = {};
            for (const item of matchedItems) {
                // Normalize field ID to match template field IDs (strip namespace prefix)
                const normalizedFieldId = this.normalizeFieldId(item.template_field_id);

                if (!dataByFieldId[normalizedFieldId]) {
                    dataByFieldId[normalizedFieldId] = [];
                }
                dataByFieldId[normalizedFieldId].push(item);
            }

            // Store in extractedData
            this.extractedData = dataByFieldId;

            // Count form fields available in current template
            const inputFields = document.querySelectorAll('input[data-field-id], textarea[data-field-id], select[data-field-id]');
            console.log(`📝 Template has ${inputFields.length} input fields`);

            // Populate the fields
            let populatedCount = 0;
            let notFoundCount = 0;
            for (const [fieldId, items] of Object.entries(dataByFieldId)) {
                // Check if this field has comparative periods (current + comparative year inputs)
                const currentInput = document.querySelector(`input[data-field-id="${fieldId}"][data-period="current"]`);
                const comparativeInput = document.querySelector(`input[data-field-id="${fieldId}"][data-period="comparative"]`);

                if (currentInput && comparativeInput) {
                    // This is a comparative field - populate both current and previous year
                    // Sort items by financial_year descending (newest first)
                    const sortedItems = [...items].sort((a, b) => (b.financial_year || 0) - (a.financial_year || 0));

                    // Populate current year (most recent)
                    if (sortedItems.length > 0) {
                        currentInput.value = sortedItems[0].extracted_value;
                        currentInput.classList.add('bg-green-50', 'border-green-400', 'border-2');
                        currentInput.style.borderColor = '#10b981';
                        currentInput.style.backgroundColor = '#d1fae5';
                        currentInput.title = `Auto-filled: ${sortedItems[0].financial_year || 'Current year'}`;
                        populatedCount++;
                    }

                    // Populate comparative year (second most recent)
                    if (sortedItems.length > 1) {
                        comparativeInput.value = sortedItems[1].extracted_value;
                        comparativeInput.classList.add('bg-green-50', 'border-green-400', 'border-2');
                        comparativeInput.style.borderColor = '#10b981';
                        comparativeInput.style.backgroundColor = '#d1fae5';
                        comparativeInput.title = `Auto-filled: ${sortedItems[1].financial_year || 'Previous year'}`;
                        populatedCount++;
                    }

                    // Show notice if more than 2 years found
                    if (sortedItems.length > 2) {
                        const notice = document.createElement('div');
                        notice.className = 'text-xs text-orange-600 mt-1 flex items-center';
                        notice.innerHTML = `
                            <svg class="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"/>
                            </svg>
                            ${sortedItems.length} years found. Showing latest 2.
                        `;
                        comparativeInput.parentElement.parentElement.appendChild(notice);
                    }
                } else {
                    // Single field (no comparative periods)
                    const fieldElement = document.querySelector(`input[data-field-id="${fieldId}"], textarea[data-field-id="${fieldId}"], select[data-field-id="${fieldId}"]`);

                    if (fieldElement) {
                        // Get field metadata for validation rules (important for dropdowns)
                        const fieldMetadata = this.getFieldMetadata(fieldId);

                        // Use the first item's value (or combine multiple years)
                        if (items.length === 1) {
                            const result = this.populateFieldElement(fieldElement, items[0].extracted_value, fieldMetadata?.validation);

                            if (result.success) {
                                // Highlight auto-filled fields with strong visual indicator
                                fieldElement.classList.add('bg-green-50', 'border-green-400', 'border-2');
                                fieldElement.style.borderColor = '#10b981';
                                fieldElement.style.backgroundColor = '#d1fae5';

                                if (result.matched && fieldElement.tagName.toLowerCase() === 'select') {
                                    fieldElement.title = `Auto-matched: "${items[0].extracted_value}" → "${result.matchedValue}"`;
                                } else {
                                    fieldElement.title = 'Auto-filled from PDF extraction';
                                }
                                populatedCount++;
                            } else {
                                // No match found for dropdown
                                fieldElement.classList.add('bg-orange-50', 'border-orange-400', 'border-2');
                                fieldElement.style.borderColor = '#fb923c';
                                fieldElement.style.backgroundColor = '#ffedd5';
                                fieldElement.title = `Extracted: "${result.extractedValue}" (no matching option found)`;
                                console.warn(`No dropdown match found for "${fieldId}": extracted="${result.extractedValue}"`);
                            }
                        } else {
                            // Multiple items for same field - pass all values as array to create dropdown
                            const allValues = items.map(item => item.extracted_value);

                            const result = this.populateFieldElement(fieldElement, allValues, fieldMetadata?.validation);

                            if (result.success) {
                                // Multi-value fields already have blue styling from _createMultiValueField
                                // No need to add additional styling since the dropdown was created successfully
                                populatedCount++;
                            } else {
                                // No match found for dropdown (validation dropdown case)
                                fieldElement.classList.add('bg-orange-50', 'border-orange-400', 'border-2');
                                fieldElement.style.borderColor = '#fb923c';
                                fieldElement.style.backgroundColor = '#ffedd5';
                                fieldElement.title = `${items.length} values extracted, but no matching dropdown option. Extracted: "${result.extractedValue}"`;
                                console.warn(`No dropdown match for "${fieldId}" from ${items.length} values: extracted="${result.extractedValue}"`);
                            }
                        }
                    } else {
                        notFoundCount++;
                    }
                }
            }

            if (populatedCount > 0) {
                console.log(`✅ Auto-filled ${populatedCount} fields in this statement (${notFoundCount} fields from other statements)`);
            } else if (matchedItems.length > 0) {
                console.log(`ℹ️ ${matchedItems.length} matched items found, but none belong to this statement template`);
            } else {
                console.log(`ℹ️ No matched data found for this job`);
            }

            // Show subtle indicator if fields were populated
            if (populatedCount > 0) {
                this.showPopulatedIndicator(populatedCount);
            }

        } catch (error) {
            console.error('Error loading extracted data:', error);
            this.showNotification('Error loading extracted data', 'error');
        }
    }

    /**
     * Show subtle populated indicator
     */
    showPopulatedIndicator(count) {
        const container = document.getElementById('template-container');
        if (!container) return;

        // Remove old indicator if exists
        const oldIndicator = container.querySelector('.data-populated-indicator');
        if (oldIndicator) oldIndicator.remove();

        // Add new indicator at top
        const indicator = document.createElement('div');
        indicator.className = 'data-populated-indicator bg-green-100 border border-green-400 text-green-800 px-4 py-2 rounded-lg mb-4 flex items-center justify-between';
        indicator.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-5 h-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
                </svg>
                <span class="font-medium">${count} field${count > 1 ? 's' : ''} auto-filled from PDF extraction</span>
            </div>
            <span class="text-xs text-green-600">Green = auto-filled | Yellow = multiple values | Orange = no dropdown match</span>
        `;

        container.insertBefore(indicator, container.firstChild);
    }

    /**
     * Show notification
     */
    showNotification(message, type = 'info') {
        // Use existing notification system if available
        if (window.notificationManager) {
            window.notificationManager.show(message, type);
        } else {
            console.log(`[${type.toUpperCase()}]`, message);
        }
    }
}
