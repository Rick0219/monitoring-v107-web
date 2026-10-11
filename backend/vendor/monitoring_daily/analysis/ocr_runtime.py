"""Shared, local-only Chinese OCR configuration and model installation."""
from pathlib import Path
import os

MODEL_DIR = Path(__file__).resolve().parents[2] / 'resources' / 'docling-models'


def create_converter():
    if not MODEL_DIR.is_dir():
        raise RuntimeError('OCR 模型资源尚未安装，请运行 V1.07 目录中的 安装OCR.ps1。')
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        options = PdfPipelineOptions(
            artifacts_path=MODEL_DIR, do_ocr=True, enable_remote_services=False,
            document_timeout=240,
            ocr_options=RapidOcrOptions(backend='onnxruntime', lang=['ch'], force_full_page_ocr=True),
            accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=4),
        )
        return DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.IMAGE],
            # The native docling-parse resource loader fails on Chinese Windows
            # installation paths. PDFium supports these paths and the OCR pipeline.
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options, backend=PyPdfiumDocumentBackend),
                            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)},
        )
    except ImportError as exc:
        raise RuntimeError('OCR 组件缺失或版本不兼容，请运行 V1.07 目录中的 安装OCR.ps1 修复。') from exc


def main():
    """Prefetch only the models this application uses, then load them to verify."""
    from docling.utils.model_downloader import download_models
    from docling.datamodel.base_models import InputFormat
    print(f'下载本地中文 OCR、版面及表格模型到：{MODEL_DIR}', flush=True)
    # Hugging Face creates long temporary filenames below the model folder.
    # Use Windows extended paths for downloads without changing OS policy.
    download_dir = Path('\\\\?\\' + str(MODEL_DIR.resolve())) if os.name == 'nt' else MODEL_DIR
    download_models(output_dir=download_dir, progress=True, with_code_formula=False,
                    with_picture_classifier=False, rapidocr_models=['onnxruntime:ch'])
    print('正在检查模型能否加载……', flush=True)
    create_converter().initialize_pipeline(InputFormat.PDF)
    print('Docling 中文 OCR 模型安装及加载检查通过。', flush=True)


if __name__ == '__main__':
    main()
