def extract_pdf_section(file_data, page_num, x, y, width, height, zoom=2.0, output_format='png'):
    """Extract a specific section from a PDF page - FIXED VERSION"""
    try:
        pdf_document = fitz.open(stream=file_data, filetype="pdf")
        
        if page_num < 0 or page_num >= len(pdf_document):
            raise ValueError(f"Page {page_num + 1} does not exist")
        
        page = pdf_document[page_num]
        
        # Get the original page dimensions
        page_rect = page.rect
        original_width = page_rect.width
        original_height = page_rect.height
        
        print(f"Original page dimensions: {original_width} x {original_height}")
        print(f"Selection coordinates received: x={x}, y={y}, w={width}, h={height}")
        
        # The coordinates are now already in PDF coordinate system from the frontend
        # No need to convert from display coordinates since frontend does the conversion
        pdf_x = x
        pdf_y = y
        pdf_width = width
        pdf_height = height
        
        print(f"Using PDF coordinates directly: x={pdf_x}, y={pdf_y}, w={pdf_width}, h={pdf_height}")
        
        # Ensure coordinates are within page bounds
        pdf_x = max(0, min(pdf_x, original_width))
        pdf_y = max(0, min(pdf_y, original_height))
        pdf_width = min(pdf_width, original_width - pdf_x)
        pdf_height = min(pdf_height, original_height - pdf_y)
        
        print(f"Clipped coordinates: x={pdf_x}, y={pdf_y}, w={pdf_width}, h={pdf_height}")
        
        # Create rectangle for the selected area
        rect = fitz.Rect(pdf_x, pdf_y, pdf_x + pdf_width, pdf_y + pdf_height)
        
        print(f"Extraction rectangle: {rect}")
        
        if output_format.lower() == 'pdf':
            # Create new PDF with just this section
            new_doc = fitz.open()
            # Create page with the size of the cropped area
            new_page = new_doc.new_page(width=pdf_width, height=pdf_height)
            
            # Calculate the source rectangle and destination rectangle
            src_rect = rect
            dest_rect = fitz.Rect(0, 0, pdf_width, pdf_height)
            
            # Insert the cropped area
            new_page.show_pdf_page(dest_rect, pdf_document, page_num, clip=src_rect)
            
            output_buffer = BytesIO()
            new_doc.save(output_buffer)
            new_doc.close()
            output_buffer.seek(0)
            
            pdf_document.close()
            return output_buffer.getvalue(), 'pdf'
        else:
            # Extract as image with high resolution
            # Use higher zoom for extraction to get better quality
            extraction_zoom = 3.0
            mat = fitz.Matrix(extraction_zoom, extraction_zoom)
            
            # Scale the rectangle for the extraction zoom
            scaled_rect = fitz.Rect(
                rect.x0 * extraction_zoom,
                rect.y0 * extraction_zoom,
                rect.x1 * extraction_zoom,
                rect.y1 * extraction_zoom
            )
            
            # Render the full page at high resolution
            pix = page.get_pixmap(matrix=mat)
            
            # Crop to the selected area
            # Convert to PIL Image for cropping
            from PIL import Image
            img_data = pix.tobytes("png")
            img = Image.open(BytesIO(img_data))
            
            # Crop the image to the selected rectangle
            crop_box = (
                int(scaled_rect.x0),
                int(scaled_rect.y0),
                int(scaled_rect.x1),
                int(scaled_rect.y1)
            )
            
            print(f"Crop box: {crop_box}")
            print(f"Image size: {img.size}")
            
            # Ensure crop box is within image bounds
            crop_box = (
                max(0, crop_box[0]),
                max(0, crop_box[1]),
                min(img.size[0], crop_box[2]),
                min(img.size[1], crop_box[3])
            )
            
            print(f"Adjusted crop box: {crop_box}")
            
            cropped_img = img.crop(crop_box)
            
            # Convert back to bytes
            output_buffer = BytesIO()
            cropped_img.save(output_buffer, format='PNG')
            output_buffer.seek(0)
            
            pdf_document.close()
            return output_buffer.getvalue(), 'png'
        
    except Exception as e:
        raise Exception(f"Error extracting section: {str(e)}")

@app.route('/extract_sections', methods=['POST'])
def extract_sections():
    """Extract selected sections and create downloadable file - FIXED VERSION"""
    try:
        print("Extract sections endpoint called")
        data = request.get_json()
        
        if not data:
            print("No JSON data received")
            return jsonify({'success': False, 'error': 'No data received'}), 400
        
        print(f"Received data keys: {data.keys()}")
        
        file_data = base64.b64decode(data['file_data'])
        selections = data['selections']
        filename = data['filename']
        output_format = data.get('output_format', 'png')
        
        print(f"Processing {len(selections)} selections for file: {filename}")
        print(f"Output format: {output_format}")
        
        if not selections:
            return jsonify({'success': False, 'error': 'No sections selected'}), 400
        
        extracted_files = []
        
        for i, selection in enumerate(selections):
            print(f"Processing selection {i+1}: {selection}")
            
            page_num = selection['page']
            # Use the PDF coordinates directly (already converted in frontend)
            x = selection['x']
            y = selection['y']
            width = selection['width']
            height = selection['height']
            zoom = selection.get('zoom', 2.0)
            
            print(f"Selection {i+1} coordinates - PDF: x={x}, y={y}, w={width}, h={height}")
            
            # Extract the section using PDF coordinates directly
            section_data, file_ext = extract_pdf_section(
                file_data, page_num, x, y, width, height, zoom, output_format
            )
            
            print(f"Extracted section {i+1}, size: {len(section_data)} bytes")
            
            # Generate filename
            section_filename = f"page_{page_num + 1}_section_{i + 1}.{file_ext}"
            
            extracted_files.append({
                'data': section_data,
                'filename': section_filename
            })
        
        print(f"Successfully extracted {len(extracted_files)} files")
        
        if len(extracted_files) == 1:
            # Single file - return directly
            print("Returning single file")
            return send_file(
                BytesIO(extracted_files[0]['data']),
                as_attachment=True,
                download_name=extracted_files[0]['filename'],
                mimetype=f'application/{output_format}' if output_format == 'pdf' else 'image/png'
            )
        else:
            # Multiple files - create ZIP
            print("Creating ZIP file")
            zip_buffer = BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_info in extracted_files:
                    zip_file.writestr(file_info['filename'], file_info['data'])
                
                # Add info file with detailed selection information
                info_content = f"Extracted sections from: {filename}\n"
                info_content += f"Total sections: {len(extracted_files)}\n\n"
                info_content += "Section Details:\n"
                info_content += "-" * 50 + "\n"
                
                for i, selection in enumerate(selections):
                    info_content += f"Section {i + 1}:\n"
                    info_content += f"  Page: {selection['page'] + 1}\n"
                    info_content += f"  PDF Position: ({selection['x']:.1f}, {selection['y']:.1f})\n"
                    info_content += f"  PDF Size: {selection['width']:.1f}x{selection['height']:.1f}\n"
                    if 'displayX' in selection:
                        info_content += f"  Display Position: ({selection['displayX']:.1f}, {selection['displayY']:.1f})\n"
                        info_content += f"  Display Size: {selection['displayWidth']:.1f}x{selection['displayHeight']:.1f}\n"
                    info_content += f"  Zoom: {selection.get('zoom', 'N/A')}\n"
                    info_content += f"  File: {extracted_files[i]['filename']}\n"
                    info_content += "-" * 30 + "\n"
                
                zip_file.writestr("extraction_info.txt", info_content)
            
            zip_buffer.seek(0)
            
            # Generate ZIP filename
            name_without_ext = os.path.splitext(filename)[0]
            zip_filename = f"{name_without_ext}_sections.zip"
            
            print(f"Returning ZIP file: {zip_filename}")
            
            return send_file(
                zip_buffer,
                as_attachment=True,
                download_name=zip_filename,
                mimetype='application/zip'
            )
    
    except Exception as e:
        print(f"Error in extract_sections: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500