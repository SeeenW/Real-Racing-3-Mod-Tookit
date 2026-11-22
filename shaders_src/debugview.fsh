
//%include utility.xsh

varying highp vec2 v_TexCoord0;
varying highp vec2 v_TexCoord1;

uniform lowp sampler2D s_Texture0;
uniform lowp sampler2D s_Texture1;

uniform highp float u_TexelDensityScale;
uniform highp float u_TexelDensityOpacity;


const highp vec4 INVALID_DATA = vec4(1.0, 0.0, 1.0, 1.0);

#if defined(DEBUGVIEW_DENSITY)
highp vec3 densityLookup(lowp sampler2D tex, highp vec2 coord)
{
#ifdef MT_GL_ES_3
	ivec2 size = textureSize(tex, 0);
	int kx = int(coord.x * float(size.x) / u_TexelDensityScale);
	int ky = int(coord.y * float(size.y) / u_TexelDensityScale);
	if ((kx % 2) == (ky % 2))
	{
		return vec3(1.0);
	}
#endif
	return vec3(0.0);
}
#endif

void main()
{
#if defined(DEBUGVIEW_ALBEDO)

	#ifdef ALBEDO_SCALE
		highp vec2 albedoTexCoord = v_TexCoord0 * mu_AlbedoScale;
	#else
		highp vec2 albedoTexCoord = v_TexCoord0;
	#endif

	gl_FragColor = vec4(texture2D(s_Texture0, albedoTexCoord).rgb, 1.0);

	#ifdef DEBUGVIEW_DENSITY
		gl_FragColor.rgb = mix(gl_FragColor.rgb, densityLookup(s_Texture0, albedoTexCoord), u_TexelDensityOpacity);
	#endif

#elif defined(DEBUGVIEW_LIGHTMAP)

	#if defined(LIGHTMAP_TINT)
		gl_FragColor = vec4(getColourFromLightmap(texture2D(s_Texture1, v_TexCoord1).rgb), 1.0);
	#else
		gl_FragColor = vec4(texture2D(s_Texture1, v_TexCoord1).rgb, 1.0);
	#endif

	#if defined(DEBUGVIEW_DENSITY)
		gl_FragColor.rgb = mix(gl_FragColor.rgb, densityLookup(s_Texture1, v_TexCoord1), u_TexelDensityOpacity);
	#endif

#else
	gl_FragColor = INVALID_DATA;
#endif
}
